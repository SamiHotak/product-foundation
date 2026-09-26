"""API keys for the public REST API. Only the SHA-256 hash of a key is stored.

A key is shown ONCE, when it is created. It belongs to a workspace (not to a person),
so it keeps working when the person who made it leaves the team. Revoke it to stop it.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ApiKey(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One API key of a workspace."""

    __tablename__ = "api_keys"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(80))
    # The first characters of the key (e.g. "pf_3kTq9x"), shown so people can tell keys apart.
    prefix: Mapped[str] = mapped_column(String(24))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    # Permission values from app.core.permissions.API_KEY_SCOPES, e.g. ["jobs:read"].
    scopes: Mapped[list[str]] = mapped_column(ARRAY(String(64)))
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def is_usable(self, now: datetime) -> bool:
        """Not revoked and not expired."""
        return self.revoked_at is None and (self.expires_at is None or self.expires_at > now)

    def __repr__(self) -> str:
        return f"<ApiKey {self.id} {self.prefix}>"
