"""Audit log: who did what, when, and from where.

Rows are written in the SAME transaction as the change they describe, so a change
can't happen without its audit row. Never put secrets or full tokens in `details`.

- `organization_id` set  -> a workspace event (shown to owners and admins).
- `organization_id` NULL -> an account event (sign-ins, password resets), part of the
  user's own data export.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin


class AuditLog(UUIDPrimaryKeyMixin, Base):
    """One audit event. Rows are never updated."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_org_created", "organization_id", "created_at"),
        Index("ix_audit_logs_actor_created", "actor_user_id", "created_at"),
    )
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    # clock_timestamp(), not now(): several events in one transaction keep their real order.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.clock_timestamp(),
        nullable=False,
        index=True,
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    # Who did it: a person, an API key, or nobody (system jobs). Kept when they are deleted.
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    actor_api_key_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("api_keys.id", ondelete="SET NULL")
    )
    # Dotted name, e.g. "member.role_changed". See app/services/audit.py for the list.
    action: Mapped[str] = mapped_column(String(64), index=True)
    target_type: Mapped[str | None] = mapped_column(String(32))
    target_id: Mapped[str | None] = mapped_column(String(64))
    # Small, safe facts: {"from": "member", "to": "admin", "email": "..."}.
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(300))
