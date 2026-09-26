"""A person who can sign in. Belongs to organizations through memberships."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A user account. Email is case-insensitive and unique."""

    __tablename__ = "users"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    email: Mapped[str] = mapped_column(CITEXT(), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    # Null for accounts that only use Google sign-in.
    password_hash: Mapped[str | None] = mapped_column(String(255))
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    google_sub: Mapped[str | None] = mapped_column(String(255), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def is_verified(self) -> bool:
        """True once the email address is confirmed."""
        return self.email_verified_at is not None

    def __repr__(self) -> str:
        return f"<User {self.id}>"  # no email in logs
