"""API key schemas (the API contract)."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# The scopes a key can have. Keep equal to app.core.permissions.API_KEY_SCOPES
# (a test checks it), so the API docs and the typed client list exactly these.
ApiKeyScope = Literal["jobs:read", "jobs:write"]


class ApiKeyCreate(BaseModel):
    """Create a key. The secret is shown once in the response."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=80, description="What the key is for.")
    scopes: list[ApiKeyScope] = Field(min_length=1, description="What the key may do.")
    expires_in_days: int | None = Field(
        default=None, ge=1, le=3650, description="Empty = never expires."
    )


class ApiKeyRead(BaseModel):
    """A key without its secret."""

    id: uuid.UUID
    name: str
    prefix: str = Field(description="The start of the key, to tell keys apart.")
    scopes: list[str]
    created_by_name: str | None
    created_at: datetime
    expires_at: datetime | None
    last_used_at: datetime | None
    expired: bool


class ApiKeyCreated(ApiKeyRead):
    """The new key. `key` is shown only this once: copy it now."""

    key: str


class ApiKeyList(BaseModel):
    """Active keys, newest first."""

    items: list[ApiKeyRead]
