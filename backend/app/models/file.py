"""Files people upload. The bytes live in S3-compatible storage; this row is the index.

Life cycle:
  uploading -> (browser uploads to S3, then calls "complete") -> scanning -> ready
                                                                          -> rejected
Without a virus scanner, "complete" goes straight to ready. Uploads that never complete
are removed by the nightly clean-up.

Every object key starts with "orgs/<organization id>/", so one workspace's files can be
listed, exported and deleted together (and never mixed with another workspace's).
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class FileStatus(StrEnum):
    """Where a file is in its life cycle."""

    UPLOADING = "uploading"  # the browser has an upload link, nothing checked yet
    SCANNING = "scanning"  # uploaded and checked; the virus scan is running
    READY = "ready"  # can be downloaded and used
    REJECTED = "rejected"  # failed a check; the stored bytes were deleted

    @property
    def counts_for_storage(self) -> bool:
        """Takes space in the workspace's plan (rejected files don't)."""
        return self is not FileStatus.REJECTED


class StoredFile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One uploaded file of a workspace."""

    __tablename__ = "files"
    __table_args__ = (Index("ix_files_org_created", "organization_id", "created_at"),)
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    # The name the person gave the file (cleaned). Only shown; never used as a path.
    filename: Mapped[str] = mapped_column(String(255))
    # Detected from the file's first bytes when it is completed (not trusted from the browser).
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    # "orgs/<organization id>/files/<file id>" in the bucket.
    storage_key: Mapped[str] = mapped_column(String(300), unique=True)
    status: Mapped[FileStatus] = mapped_column(
        Enum(
            FileStatus,
            name="file_status",
            native_enum=False,
            length=16,
            create_constraint=True,
            values_callable=lambda enum: [member.value for member in enum],
            validate_strings=True,
        ),
        default=FileStatus.UPLOADING,
        index=True,
    )
    # Why a file was rejected (safe to show).
    status_message: Mapped[str | None] = mapped_column(String(300))
    upload_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:
        return f"<StoredFile {self.id} {self.status.value}>"  # no file name in logs
