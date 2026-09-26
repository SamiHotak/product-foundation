"""GDPR deletion, API side: schedule or cancel deleting an account or a workspace.

Nothing is deleted right away. The date is set `deletion_grace_days` in the future and an
email explains how to cancel. The nightly job (app/services/purge.py) deletes what is due.

Safety:
- The caller must type the exact confirmation text (their email / the workspace name).
- An account that owns a workspace with other people can't be scheduled: transfer
  ownership first, so no team loses its workspace by surprise.
"""

from datetime import datetime, timedelta

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError, ConflictError
from app.core.permissions import Permission
from app.models.user import User
from app.repositories.organizations import OrganizationRepository
from app.services import email as emails
from app.services.audit import AuditAction, AuditService
from app.services.email import EmailSender
from app.services.organizations import OrgContext
from app.services.sessions import utcnow


class ConfirmationMismatchError(AppError):
    """The typed confirmation text is wrong."""

    status_code = status.HTTP_400_BAD_REQUEST
    code = "confirmation_mismatch"


def _date(value: datetime) -> str:
    return f"{value:%d %B %Y}"


class DeletionService:
    """Schedule and cancel deletions. One instance per request."""

    def __init__(
        self,
        db: AsyncSession,
        settings: Settings,
        email_sender: EmailSender,
        audit: AuditService,
    ) -> None:
        self._db = db
        self._settings = settings
        self._email = email_sender
        self._audit = audit
        self._orgs = OrganizationRepository(db)

    def _when(self) -> datetime:
        return utcnow() + timedelta(days=self._settings.deletion_grace_days)

    # --- account -------------------------------------------------------------------------

    async def schedule_account(self, user: User, confirm: str) -> User:
        """Delete this account after the grace period."""
        if confirm.strip().lower() != user.email.lower():
            raise ConfirmationMismatchError("Type your email address exactly to confirm.")
        blocking = await self._orgs.owned_with_others(user.id)
        if blocking:
            names = ", ".join(f"“{o.name}”" for o in blocking)
            raise ConflictError(
                f"You own {names}, where other people work too. Transfer ownership "
                "(Settings → Workspace) or delete those workspaces first.",
                details={"workspaces": [{"id": str(o.id), "name": o.name} for o in blocking]},
            )
        if user.deletion_scheduled_at is None:
            when = user.deletion_scheduled_at = self._when()
            await self._audit.record(
                AuditAction.ACCOUNT_DELETION_SCHEDULED,
                organization_id=None,
                actor_user_id=user.id,
                details={"deletion_scheduled_at": when.isoformat()},
            )
            await self._db.commit()
            await self._email.send(
                emails.account_deletion_email(
                    to=user.email,
                    name=user.name,
                    when=_date(when),
                    settings_url=f"{self._settings.app_url}/settings/privacy",
                    app_name=self._settings.app_name,
                )
            )
        return user

    async def cancel_account(self, user: User) -> User:
        """Keep the account."""
        if user.deletion_scheduled_at is not None:
            user.deletion_scheduled_at = None
            await self._audit.record(
                AuditAction.ACCOUNT_DELETION_CANCELLED, organization_id=None, actor_user_id=user.id
            )
            await self._db.commit()
        return user

    # --- workspace -----------------------------------------------------------------------

    async def schedule_org(self, ctx: OrgContext, confirm: str) -> OrgContext:
        """Delete the active workspace and all its data after the grace period (owner only)."""
        ctx.require(Permission.ORG_DELETE)
        org = await self._orgs.lock(ctx.organization.id)
        assert org is not None
        if confirm.strip() != org.name:
            raise ConfirmationMismatchError("Type the workspace name exactly to confirm.")
        if org.deletion_scheduled_at is None:
            when = org.deletion_scheduled_at = self._when()
            await self._audit.record(
                AuditAction.ORG_DELETION_SCHEDULED,
                organization_id=org.id,
                actor_user_id=ctx.user.id,
                details={"deletion_scheduled_at": when.isoformat()},
            )
            await self._db.commit()
            await self._email.send(
                emails.workspace_deletion_email(
                    to=ctx.user.email,
                    name=ctx.user.name,
                    organization_name=org.name,
                    when=_date(when),
                    settings_url=f"{self._settings.app_url}/settings/privacy",
                    app_name=self._settings.app_name,
                )
            )
        return ctx

    async def cancel_org(self, ctx: OrgContext) -> OrgContext:
        """Keep the workspace (owner only)."""
        ctx.require(Permission.ORG_DELETE)
        org = await self._orgs.lock(ctx.organization.id)
        assert org is not None
        if org.deletion_scheduled_at is not None:
            org.deletion_scheduled_at = None
            await self._audit.record(
                AuditAction.ORG_DELETION_CANCELLED,
                organization_id=org.id,
                actor_user_id=ctx.user.id,
            )
            await self._db.commit()
        return ctx
