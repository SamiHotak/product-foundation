"""One-time tokens sent by email (verify email, reset password). Only hashes are stored."""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class TokenPurpose(StrEnum):
    """What a token can be used for."""

    VERIFY_EMAIL = "verify_email"
    RESET_PASSWORD = "reset_password"  # noqa: S105 - a purpose name, not a password


class AuthToken(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A single-use, expiring token."""

    __tablename__ = "auth_tokens"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    purpose: Mapped[TokenPurpose] = mapped_column(
        Enum(
            TokenPurpose,
            name="token_purpose",
            native_enum=False,
            length=32,
            create_constraint=True,
            values_callable=lambda enum: [member.value for member in enum],
            validate_strings=True,
        )
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
