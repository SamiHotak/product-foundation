"""Switches admins can flip at runtime, without a restart (e.g. the AI kill switch).

Settings from environment variables need a restart; these don't. Keep the list short:
every flag is read on every request that needs it.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Flag(StrEnum):
    """Every runtime switch. Missing row = the default below."""

    AI_PAUSED = "ai_paused"  # True: every LLM call is refused (the kill switch)


FLAG_DEFAULTS: dict[Flag, bool] = {Flag.AI_PAUSED: False}


class SystemFlag(Base):
    """One runtime switch and who changed it last."""

    __tablename__ = "system_flags"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
