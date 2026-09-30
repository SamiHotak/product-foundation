"""File schemas (the API contract)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.file import FileStatus


class UploadStart(BaseModel):
    """Ask for an upload link for one file."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    filename: str = Field(min_length=1, max_length=300)
    size_bytes: int = Field(ge=1, description="The exact size of the file.")


class FileRead(BaseModel):
    """One file of the workspace."""

    id: uuid.UUID
    filename: str
    content_type: str
    size_bytes: int
    status: FileStatus
    status_message: str | None
    uploaded_by_name: str | None
    created_at: datetime
    can_delete: bool = Field(description="The caller may delete this file.")


class UploadForm(BaseModel):
    """Send the file as multipart/form-data: every field below, then `file` LAST."""

    url: str
    fields: dict[str, str]
    expires_at: datetime


class UploadStarted(BaseModel):
    """The new file (status "uploading") and where to upload it."""

    file: FileRead
    upload: UploadForm


class UploadCompleted(BaseModel):
    """The file after its checks. `job_id` is set while the virus scan runs."""

    file: FileRead
    job_id: uuid.UUID | None = None


class FileList(BaseModel):
    """Files of the workspace, newest first."""

    items: list[FileRead]
    max_bytes: int = Field(description="Largest file one upload may have.")
    allowed_extensions: list[str]
    enabled: bool = Field(description="False: file storage is not set up on this server.")


class DownloadLink(BaseModel):
    """A short-lived link that downloads the file."""

    url: str
    expires_at: datetime
