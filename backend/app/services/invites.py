"""Invites: invite people by email, and let them join (signed in, or with a new account).

Security rules:
- The link token is random (256 bits), single use, expires, and only its hash is stored.
- An invite can only be accepted by the account with the SAME email address.
- Creating an account from an invite needs no extra confirmation email: the invite link
  was sent to that inbox, so opening it proves the address.
- Invites per workspace per hour are limited, so nobody can use us to spam inboxes.
- Preview answers only for a valid open token (nothing to find by guessing).
"""

import uuid
from datetime import datetime, timedelta

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError, ConflictError, NotFoundError, RateLimitedError
from app.core.logging import get_logger
from app.core.permissions import Permission
from app.core.rate_limit import RateLimiter
from app.core.security import hash_password, hash_token, new_token
from app.models.invite import Invite
from app.models.organization import Organization, Role
from app.models.session import UserSession
from app.models.user import User
from app.repositories.invites import InviteRepository
from app.repositories.organizations import OrganizationRepository
from app.repositories.users import UserRepository
from app.schemas.team import InvitePreview, InviteRead
from app.services import email as emails
from app.services.audit import AuditAction, AuditService
from app.services.email import EmailSender
from app.services.organizations import OrgContext
from app.services.sessions import utcnow

logger = get_logger(__name__)

INVALID_INVITE = (
    "This invite link is not valid any more. Ask the person who invited you for a new one."
)


class InvalidInviteError(AppError):
    """Wrong, used, cancelled or expired invite link."""

    status_code = status.HTTP_400_BAD_REQUEST
    code = "invalid_invite"


class InviteEmailMismatchError(AppError):
    """Signed in with a different email than the invite was sent to."""

    status_code = status.HTTP_403_FORBIDDEN
    code = "invite_email_mismatch"


class AccountExistsError(AppError):
    """Tried to create an account from an invite, but the email already has one."""

    status_code = status.HTTP_409_CONFLICT
    code = "account_exists"


def invite_read(invite: Invite, inviter: User | None) -> InviteRead:
    """The API shape of an open invite."""
    return InviteRead(
        id=invite.id,
        email=invite.email,
        role=invite.role,
        invited_by_name=inviter.name if inviter else None,
        created_at=invite.created_at,
        expires_at=invite.expires_at,
    )


class InviteService:
    """Invite operations. One instance per request."""

    def __init__(
        self,
        db: AsyncSession,
        settings: Settings,
        email_sender: EmailSender,
        limiter: RateLimiter,
        audit: AuditService,
    ) -> None:
        self._db = db
        self._settings = settings
        self._email = email_sender
        self._limiter = limiter
        self._audit = audit
        self._invites = InviteRepository(db)
        self._orgs = OrganizationRepository(db)
        self._users = UserRepository(db)

    # --- workspace side (owners and admins) -----------------------------------------------

    async def _count_send(self, ctx: OrgContext) -> None:
        wait = await self._limiter.hit(
            f"invites:{ctx.organization.id}",
            limit=self._settings.invites_per_org_per_hour,
            window_seconds=3600,
        )
        if wait is not None:
            raise RateLimitedError(
                "This workspace sent a lot of invites in the last hour. Try again later.",
                retry_after=wait,
            )

    def _issue(self, invite: Invite, now: datetime) -> str:
        token = new_token()
        invite.token_hash = hash_token(token)
        invite.expires_at = now + timedelta(days=self._settings.invite_days)
        return token

    async def _send(self, ctx: OrgContext, invite: Invite, token: str) -> None:
        await self._email.send(
            emails.invite_email(
                to=invite.email,
                inviter_name=ctx.user.name,
                organization_name=ctx.organization.name,
                role=invite.role.value,
                url=f"{self._settings.app_url}/invite?token={token}",
                app_name=self._settings.app_name,
                days=self._settings.invite_days,
            )
        )

    async def create(self, ctx: OrgContext, email: str, role: Role) -> InviteRead:
        """Invite someone. A new invite to the same email replaces the old one."""
        ctx.require(Permission.MEMBERS_INVITE)
        if role is Role.OWNER:
            raise ConflictError("Invite as admin or member. Ownership moves with a transfer.")
        email = email.strip()
        await self._orgs.lock(ctx.organization.id)
        existing = await self._users.get_by_email(email)
        if existing and await self._orgs.get_membership(ctx.organization.id, existing.id):
            raise ConflictError(f"{email} is already in this workspace.")
        await self._count_send(ctx)
        now = utcnow()
        old = await self._invites.get_unfinished_for_email(ctx.organization.id, email)
        if old is not None:
            old.revoked_at = now
            await self._db.flush()  # free the "one open invite per email" slot first
        invite = Invite(
            organization_id=ctx.organization.id,
            email=email,
            role=role,
            invited_by_id=ctx.user.id,
        )
        token = self._issue(invite, now)
        await self._invites.add(invite)
        await self._audit.record(
            AuditAction.INVITE_CREATED,
            organization_id=ctx.organization.id,
            actor_user_id=ctx.user.id,
            target_type="invite",
            target_id=invite.id,
            details={"email": email, "role": role.value},
        )
        await self._db.commit()
        await self._send(ctx, invite, token)
        logger.info("invite_created", invite_id=str(invite.id))
        return invite_read(invite, ctx.user)

    async def list_open(self, ctx: OrgContext) -> list[InviteRead]:
        """Invites nobody has accepted yet."""
        ctx.require(Permission.MEMBERS_INVITE)
        rows = await self._invites.list_open(ctx.organization.id, utcnow())
        return [invite_read(i, u) for i, u in rows]

    async def _open_invite(self, ctx: OrgContext, invite_id: uuid.UUID) -> Invite:
        invite = await self._invites.get(invite_id, organization_id=ctx.organization.id)
        if invite is None or invite.accepted_at is not None or invite.revoked_at is not None:
            raise NotFoundError("This invite does not exist or was already used.")
        return invite

    async def resend(self, ctx: OrgContext, invite_id: uuid.UUID) -> InviteRead:
        """Send the invite again with a fresh link (the old link stops working)."""
        ctx.require(Permission.MEMBERS_INVITE)
        invite = await self._open_invite(ctx, invite_id)
        await self._count_send(ctx)
        token = self._issue(invite, utcnow())
        invite.invited_by_id = ctx.user.id  # the new email says it comes from this person
        await self._audit.record(
            AuditAction.INVITE_RESENT,
            organization_id=ctx.organization.id,
            actor_user_id=ctx.user.id,
            target_type="invite",
            target_id=invite.id,
            details={"email": invite.email},
        )
        await self._db.commit()
        await self._send(ctx, invite, token)
        return invite_read(invite, ctx.user)

    async def revoke(self, ctx: OrgContext, invite_id: uuid.UUID) -> None:
        """Cancel an invite. Its link stops working."""
        ctx.require(Permission.MEMBERS_INVITE)
        invite = await self._open_invite(ctx, invite_id)
        invite.revoked_at = utcnow()
        await self._audit.record(
            AuditAction.INVITE_REVOKED,
            organization_id=ctx.organization.id,
            actor_user_id=ctx.user.id,
            target_type="invite",
            target_id=invite.id,
            details={"email": invite.email},
        )
        await self._db.commit()

    # --- invited person's side ------------------------------------------------------------

    async def _find_open(
        self, token: str, *, lock: bool = False
    ) -> tuple[Invite, Organization, User | None]:
        found = await self._invites.get_by_token_hash(hash_token(token), for_update=lock)
        if found is None or not found[0].is_open(utcnow()):
            raise InvalidInviteError(INVALID_INVITE)
        return found

    async def preview(self, token: str) -> InvitePreview:
        """What the invite page shows."""
        invite, org, inviter = await self._find_open(token)
        account = await self._users.get_by_email(invite.email)
        return InvitePreview(
            organization_name=org.name,
            invited_by_name=inviter.name if inviter else None,
            email=invite.email,
            role=invite.role,
            expires_at=invite.expires_at,
            account_exists=account is not None and account.is_verified,
        )

    async def _join(self, invite: Invite, org: Organization, user: User) -> None:
        """Add the user (if not a member yet) and mark the invite used."""
        now = utcnow()
        already = await self._orgs.get_membership(org.id, user.id)
        if already is None:
            await self._orgs.add_member(org.id, user.id, invite.role)
            await self._audit.record(
                AuditAction.MEMBER_JOINED,
                organization_id=org.id,
                actor_user_id=user.id,
                target_type="user",
                target_id=user.id,
                details={
                    "email": user.email,
                    "role": invite.role.value,
                    "invite_id": str(invite.id),
                },
            )
        invite.accepted_at = now
        invite.accepted_by_id = user.id

    async def accept(self, token: str, user: User, user_session: UserSession) -> None:
        """The signed-in user joins the workspace, which becomes their active one."""
        invite, org, _ = await self._find_open(token, lock=True)
        if invite.email.lower() != user.email.lower():
            raise InviteEmailMismatchError(
                f"This invite is for {invite.email}, but you are signed in as {user.email}. "
                "Sign out, then sign in with the invited email address."
            )
        await self._orgs.lock(org.id)
        await self._join(invite, org, user)
        user_session.active_organization_id = org.id
        await self._db.commit()
        logger.info("invite_accepted", invite_id=str(invite.id), user_id=str(user.id))

    async def signup(self, *, token: str, name: str, password: str) -> tuple[User, Organization]:
        """Create an account from an invite and join. The caller starts a session."""
        invite, org, _ = await self._find_open(token, lock=True)
        user = await self._users.get_by_email(invite.email)
        if user is not None and user.is_verified:
            raise AccountExistsError(
                "You already have an account with this email. Sign in to accept the invite."
            )
        now = utcnow()
        if user is None:
            user = User(name=name, email=invite.email, password_hash=hash_password(password))
            await self._users.add(user)
        else:
            # Signed up before but never confirmed: the invite link proves the inbox is theirs.
            user.name = name
            user.password_hash = hash_password(password)
        user.email_verified_at = now
        user.last_login_at = now
        await self._orgs.lock(org.id)
        await self._join(invite, org, user)
        await self._audit.record(
            AuditAction.AUTH_LOGIN,
            organization_id=None,
            actor_user_id=user.id,
            details={"method": "invite"},
        )
        await self._db.commit()
        logger.info("invite_signup", invite_id=str(invite.id), user_id=str(user.id))
        return user, org
