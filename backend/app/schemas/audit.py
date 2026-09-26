"""Audit log schemas (the API contract)."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AuditActor(BaseModel):
    """Who did it."""

    type: str = Field(description='"user", "api_key", "deleted_user" or "system".')
    name: str | None
    email: str | None = None


class AuditEntry(BaseModel):
    """One event."""

    id: uuid.UUID
    created_at: datetime
    action: str = Field(description='e.g. "member.role_changed". See AuditAction.')
    actor: AuditActor
    target_type: str | None
    target_id: str | None
    details: dict[str, Any]
    ip_address: str | None


class AuditPage(BaseModel):
    """Newest first. Pass `next_cursor` as `before` to get the next page."""

    items: list[AuditEntry]
    next_cursor: str | None
