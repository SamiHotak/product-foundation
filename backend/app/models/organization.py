"""Organizations (workspaces) and who belongs to them."""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Role(StrEnum):
    """What a member may do. The rules live in app/core/permissions.py."""

    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class Organization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A workspace. All product data belongs to exactly one organization."""

    __tablename__ = "organizations"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    name: Mapped[str] = mapped_column(String(80))
    # GDPR: the owner asked to delete the workspace; the nightly job deletes it after this.
    deletion_scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Membership(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A user's role in one organization."""

    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="uq_memberships_org_user"),
    )
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[Role] = mapped_column(
        Enum(
            Role,
            name="membership_role",
            native_enum=False,
            length=16,
            create_constraint=True,
            values_callable=lambda enum: [member.value for member in enum],
            validate_strings=True,
        )
    )
