"""Privacy schemas: data exports and account / workspace deletion (the API contract)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.data_export import ExportScope


class ExportRead(BaseModel):
    """A data export. Download it when `ready` is true."""

    id: uuid.UUID
    scope: ExportScope
    job_id: uuid.UUID | None = Field(description="Follow progress with GET /api/jobs/{id}.")
    filename: str
    ready: bool
    size_bytes: int | None
    created_at: datetime
    expires_at: datetime
    download_url: str


class ExportList(BaseModel):
    """Your recent exports (and the workspace's, if you may see them). Newest first."""

    items: list[ExportRead]


class DeletionRequest(BaseModel):
    """Type the confirmation text exactly (the email address, or the workspace name)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    confirm: str = Field(min_length=1, max_length=320)


class DeletionStatus(BaseModel):
    """When the deletion will happen (null = not scheduled)."""

    deletion_scheduled_at: datetime | None
