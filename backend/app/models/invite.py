"""Invitations to join a workspace. The email link holds a random token; we store its hash."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.organization import Role


class Invite(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An open, accepted, revoked or expired invitation.

    Open = not accepted, not revoked, not expired. At most one open invite per email
    and workspace (a new invite replaces the old one).
    """

    __tablename__ = "invites"
    __table_args__ = (
        # One open invite per (workspace, email). Revoked or accepted ones don't count.
        Index(
            "uq_invites_open_org_email",
            "organization_id",
            "email",
            unique=True,
            postgresql_where=text("accepted_at IS NULL AND revoked_at IS NULL"),
        ),
    )
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    email: Mapped[str] = mapped_column(CITEXT())
    # owner is never invited: ownership moves with "transfer ownership".
    role: Mapped[Role] = mapped_column(
        Enum(
            Role,
            name="invite_role",
            native_enum=False,
            length=16,
            create_constraint=True,
            values_callable=lambda enum: [member.value for member in enum],
            validate_strings=True,
        )
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    invited_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def is_open(self, now: datetime) -> bool:
        """Can still be accepted."""
        return self.accepted_at is None and self.revoked_at is None and self.expires_at > now
