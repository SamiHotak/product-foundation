"""Audit log: record events in the same transaction as the change, and read them back.

Add an action here when a product adds something worth auditing (exports, deletions,
settings changes, anything security-related). The frontend shows a label per action.
"""

import base64
import binascii
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.audit_log import AuditLog
from app.repositories.audit import AuditRepository, AuditRow
from app.schemas.audit import AuditActor, AuditEntry

# System events (no person, no key) carry this flag in `details`.
SYSTEM_FLAG = "system"


class AuditAction(StrEnum):
    """Everything the audit log records. Format: "<area>.<what happened>"."""

    AUTH_LOGIN = "auth.login"
    AUTH_PASSWORD_RESET = "auth.password_reset"  # noqa: S105 - an event name
    ORG_CREATED = "org.created"
    ORG_RENAMED = "org.renamed"
    ORG_OWNERSHIP_TRANSFERRED = "org.ownership_transferred"
    ORG_EXPORTED = "org.exported"
    ORG_DELETION_SCHEDULED = "org.deletion_scheduled"
    ORG_DELETION_CANCELLED = "org.deletion_cancelled"
    INVITE_CREATED = "invite.created"
    INVITE_RESENT = "invite.resent"
    INVITE_REVOKED = "invite.revoked"
    MEMBER_JOINED = "member.joined"
    MEMBER_ROLE_CHANGED = "member.role_changed"
    MEMBER_REMOVED = "member.removed"
    MEMBER_LEFT = "member.left"
    API_KEY_CREATED = "api_key.created"
    API_KEY_REVOKED = "api_key.revoked"
    ACCOUNT_EXPORTED = "account.exported"
    ACCOUNT_DELETION_SCHEDULED = "account.deletion_scheduled"
    ACCOUNT_DELETION_CANCELLED = "account.deletion_cancelled"


@dataclass(frozen=True)
class RequestMeta:
    """Where a request came from (stored with each audit event)."""

    ip: str | None = None
    user_agent: str | None = None


def audit_entry(row: AuditRow) -> AuditEntry:
    """The API shape of one event, with a readable actor."""
    entry, user, key = row
    if user is not None:
        actor = AuditActor(type="user", name=user.name, email=user.email)
    elif key is not None:
        actor = AuditActor(type="api_key", name=f"API key “{key.name}” ({key.prefix}…)")
    elif entry.details.get(SYSTEM_FLAG):
        actor = AuditActor(type="system", name=None)
    else:  # the person's account was deleted since (the link is set to NULL)
        actor = AuditActor(type="deleted_user", name=None)
    return AuditEntry(
        id=entry.id,
        created_at=entry.created_at,
        action=entry.action,
        actor=actor,
        target_type=entry.target_type,
        target_id=entry.target_id,
        details={k: v for k, v in entry.details.items() if k != SYSTEM_FLAG},
        ip_address=entry.ip_address,
    )


class InvalidCursorError(AppError):
    """The `before` cursor is not one we handed out."""

    code = "invalid_cursor"


def encode_cursor(created_at: datetime, row_id: uuid.UUID) -> str:
    """Opaque "next page" cursor."""
    raw = f"{created_at.isoformat()}|{row_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    """Inverse of encode_cursor. Raises InvalidCursorError for anything else."""
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        stamp, _, row_id = raw.partition("|")
        return datetime.fromisoformat(stamp), uuid.UUID(row_id)
    except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
        raise InvalidCursorError("This page link is not valid. Reload the audit log.") from exc


class AuditService:
    """Writes and reads audit events. One instance per request."""

    def __init__(self, db: AsyncSession, meta: RequestMeta) -> None:
        self._repo = AuditRepository(db)
        self._meta = meta

    async def record(
        self,
        action: AuditAction,
        *,
        organization_id: uuid.UUID | None,
        actor_user_id: uuid.UUID | None = None,
        actor_api_key_id: uuid.UUID | None = None,
        target_type: str | None = None,
        target_id: uuid.UUID | str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Add an event. It is saved when the caller commits (together with the change)."""
        await self._repo.add(
            AuditLog(
                organization_id=organization_id,
                actor_user_id=actor_user_id,
                actor_api_key_id=actor_api_key_id,
                action=action.value,
                target_type=target_type,
                target_id=str(target_id) if target_id is not None else None,
                details=details or {},
                ip_address=(self._meta.ip or "")[:64] or None,
                user_agent=(self._meta.user_agent or "")[:300] or None,
            )
        )

    async def list_for_org(
        self,
        organization_id: uuid.UUID,
        *,
        limit: int,
        before: str | None = None,
        action_prefix: str | None = None,
    ) -> tuple[list[AuditEntry], str | None]:
        """One page of the workspace's events (newest first) and the cursor for the next page."""
        rows = await self._repo.list_for_org(
            organization_id,
            limit=limit + 1,
            before=decode_cursor(before) if before else None,
            action_prefix=action_prefix,
        )
        page = rows[:limit]
        next_cursor = None
        if len(rows) > limit and page:
            last = page[-1][0]
            next_cursor = encode_cursor(last.created_at, last.id)
        return [audit_entry(row) for row in page], next_cursor
