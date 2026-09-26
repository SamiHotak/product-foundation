"""Background job: one row per long-running task, so the UI can show live status.

A Celery task receives the job id, and writes its status and progress here.
The Celery task id is the same UUID as the job id, so logs are easy to match.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class JobStatus(StrEnum):
    """Life cycle: queued -> running -> done | failed (a retry goes back to queued)."""

    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"

    @property
    def is_finished(self) -> bool:
        """True when the job will not change any more."""
        return self in (JobStatus.DONE, JobStatus.FAILED)


class Job(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A background job and its live status. Always belongs to one organization."""

    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint("progress >= 0 AND progress <= 100", name="progress_range"),
        Index("ix_jobs_created_at", "created_at"),
    )
    # Load created_at / updated_at back from the database on every INSERT/UPDATE
    # (Postgres RETURNING), so async code never triggers a lazy load.
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    # Who started it (None for system jobs, e.g. scheduled ones).
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[JobStatus] = mapped_column(
        Enum(
            JobStatus,
            name="job_status",
            native_enum=False,
            length=16,
            create_constraint=True,
            values_callable=lambda enum: [member.value for member in enum],
            validate_strings=True,
        ),
        default=JobStatus.QUEUED,
        index=True,
    )
    progress: Mapped[int] = mapped_column(Integer, default=0)
    # Short, user-facing text ("Step 3 of 5", "Retrying after a temporary error").
    message: Mapped[str | None] = mapped_column(String(500))
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # Safe, user-facing error text. Full details go to the worker logs only.
    error: Mapped[str | None] = mapped_column(String(1000))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:
        return f"<Job {self.id} {self.kind} {self.status.value} {self.progress}%>"


def new_job_id() -> uuid.UUID:
    """A fresh job id (also used as the Celery task id)."""
    return uuid.uuid4()
