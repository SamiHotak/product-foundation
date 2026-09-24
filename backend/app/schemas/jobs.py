"""Job schemas (API contract for background job status)."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.job import JobStatus


class JobRead(BaseModel):
    """A background job and its live status."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str = Field(description="What the job does, e.g. `example`.")
    status: JobStatus
    progress: int = Field(ge=0, le=100, description="0-100.")
    message: str | None = Field(description="Short status text for people.")
    result: dict[str, Any] | None = Field(description="Small JSON result when done.")
    error: str | None = Field(description="Safe error text when failed.")
    attempts: int = Field(description="How many times a worker started this job.")
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class JobList(BaseModel):
    """Newest jobs first."""

    items: list[JobRead]


class ExampleJobCreate(BaseModel):
    """Start the example job (counts through steps, one per second)."""

    model_config = ConfigDict(extra="forbid")

    steps: int = Field(default=5, ge=1, le=20, description="How many one-second steps.")
    fail: bool = Field(default=False, description="Fail halfway, to see the failed state.")
