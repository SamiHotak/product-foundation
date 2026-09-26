"""GDPR data exports: a ZIP built by a background job, downloadable for a few days.

The ZIP is stored in Postgres for now (small files, works across containers without
extra setup). Phase 4B moves file storage to S3; only `ExportRepository` changes then.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, LargeBinary, String
from sqlalchemy.orm import Mapped, deferred, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ExportScope(StrEnum):
    """Whose data is in the export."""

    ACCOUNT = "account"  # one person: profile, memberships, sign-ins, their activity
    ORGANIZATION = "organization"  # one workspace: members, invites, keys, audit log, data


class DataExport(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One export. `content` is empty until the job has finished."""

    __tablename__ = "data_exports"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    scope: Mapped[ExportScope] = mapped_column(
        Enum(
            ExportScope,
            name="export_scope",
            native_enum=False,
            length=16,
            create_constraint=True,
            values_callable=lambda enum: [member.value for member in enum],
            validate_strings=True,
        )
    )
    # Account exports belong to the user; workspace exports to the workspace.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    requested_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    filename: Mapped[str] = mapped_column(String(120))
    # Deferred: listing exports never loads the file itself.
    content: Mapped[bytes | None] = deferred(mapped_column(LargeBinary))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
