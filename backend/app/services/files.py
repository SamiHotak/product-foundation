"""Files: upload links, checks after upload, listing, download links and deleting.

The flow (see app/services/storage.py for why the browser talks to the storage directly):
1. `start_upload()`  checks name, type, size and the plan's storage, saves a row
                     ("uploading") and returns a signed upload form.
2. The browser uploads the file straight to the storage, to a STAGING key.
3. `complete()`      copies the staged object to its final key (browsers can't write
                     there), then checks the copy: is it the size we expect, are its first
                     bytes really the type its name says? Then either "ready", or
                     "scanning" while a virus scan job runs (ClamAV).
Copying BEFORE checking matters: the upload form stays valid for a few minutes, so a
browser could send other bytes to the staging key after we checked it. Those bytes are
never copied, and old staged objects are deleted every night.
Anything that fails a check is deleted from the storage and marked "rejected".
"""

import asyncio
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import (
    AppError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ServiceUnavailableError,
)
from app.core.logging import get_logger
from app.core.permissions import Permission
from app.core.plans import PlanCatalog
from app.models.file import FileStatus, StoredFile
from app.models.user import User
from app.repositories.files import FileRepository
from app.repositories.organizations import OrganizationRepository
from app.schemas.files import (
    DownloadLink,
    FileList,
    FileRead,
    UploadCompleted,
    UploadForm,
    UploadStarted,
)
from app.services import file_types
from app.services.audit import AuditAction, AuditService
from app.services.jobs import JobService
from app.services.organizations import Caller
from app.services.storage import ObjectStorage, StorageError, org_prefix, upload_prefix
from app.services.usage import UsageService

logger = get_logger(__name__)

FILES_OFF = "File uploads are not set up on this server yet."
STORAGE_DOWN = "The file storage is not reachable right now. Try again in a minute."


class FileRejectedError(AppError):
    """The uploaded file failed a check (size, type) and was deleted."""

    code = "file_rejected"


class InvalidFileError(AppError):
    """The file can't be uploaded (name, type or size not allowed)."""

    code = "invalid_file"


def utcnow() -> datetime:
    """Current time (UTC)."""
    return datetime.now(UTC)


def storage_key(organization_id: uuid.UUID, file_id: uuid.UUID) -> str:
    """Where a file lives in the bucket. Never contains the user's file name."""
    return f"{org_prefix(organization_id)}files/{file_id}"


def upload_key(organization_id: uuid.UUID, file_id: uuid.UUID) -> str:
    """Where the browser uploads a file first (staging; never served or trusted)."""
    return f"{upload_prefix(organization_id)}{file_id}"


def can_delete(caller: Caller, file: StoredFile) -> bool:
    """Owners and admins delete any file; members their own. API keys can't delete."""
    if caller.user is None:
        return False
    if caller.can(Permission.FILES_MANAGE):
        return True
    return caller.can(Permission.FILES_WRITE) and file.uploaded_by_id == caller.user.id


def file_read(file: StoredFile, uploader: User | None, caller: Caller) -> FileRead:
    """The API shape of a file."""
    return FileRead(
        id=file.id,
        filename=file.filename,
        content_type=file.content_type,
        size_bytes=file.size_bytes,
        status=file.status,
        status_message=file.status_message,
        uploaded_by_name=uploader.name if uploader else None,
        created_at=file.created_at,
        can_delete=can_delete(caller, file),
    )


class FileService:
    """File operations for one request."""

    def __init__(
        self,
        db: AsyncSession,
        settings: Settings,
        storage: ObjectStorage | None,
        audit: AuditService,
        catalog: PlanCatalog,
        jobs: JobService,
        *,
        scan: bool,
    ) -> None:
        self._db = db
        self._settings = settings
        self._storage = storage
        self._audit = audit
        self._files = FileRepository(db)
        self._usage = UsageService(db, catalog)
        self._jobs = jobs
        self._scan = scan

    def _require_storage(self) -> ObjectStorage:
        if self._storage is None:
            raise ServiceUnavailableError(FILES_OFF)
        return self._storage

    async def _call[T](self, fn: Callable[..., T], *args: Any, **kw: Any) -> T:
        """Run a blocking storage call in a thread; storage problems become a 503."""
        try:
            result: T = await asyncio.to_thread(fn, *args, **kw)
        except StorageError as exc:
            logger.error("storage_error", error=str(exc))
            raise ServiceUnavailableError(STORAGE_DOWN) from exc
        return result

    async def list_files(self, caller: Caller, *, limit: int = 500) -> FileList:
        """The workspace's files."""
        caller.require(Permission.FILES_READ)
        rows = await self._files.list(caller.organization.id, limit=limit)
        return FileList(
            items=[file_read(f, u, caller) for f, u in rows],
            max_bytes=self._settings.files_max_bytes,
            allowed_extensions=file_types.allowed_extensions(),
            enabled=self._storage is not None,
        )

    async def start_upload(self, caller: Caller, filename: str, size_bytes: int) -> UploadStarted:
        """Check the file, reserve its space, and return a signed upload form."""
        caller.require(Permission.FILES_WRITE)
        storage = self._require_storage()
        name = file_types.clean_filename(filename)
        if not name:
            raise InvalidFileError("This file name can't be used. Rename the file and try again.")
        kind = file_types.type_for_name(name)
        if kind is None:
            allowed = ", ".join(file_types.allowed_extensions())
            raise InvalidFileError(f"This type of file can't be uploaded. Allowed: {allowed}.")
        max_bytes = self._settings.files_max_bytes
        if size_bytes > max_bytes:
            raise InvalidFileError(
                f"This file is too big. The largest file you can upload is "
                f"{max_bytes / 1024 / 1024:g} MB."
            )
        org_id = caller.organization.id
        # Lock the workspace row: two uploads at once can't both take the last free space.
        await OrganizationRepository(self._db).lock(org_id)
        await self._usage.check_storage(org_id, size_bytes)
        now = utcnow()
        expires = now + timedelta(minutes=self._settings.files_upload_minutes)
        file_id = uuid.uuid4()
        file = await self._files.add(
            StoredFile(
                id=file_id,
                organization_id=org_id,
                uploaded_by_id=caller.user_id,
                filename=name,
                content_type=kind.content_type,
                size_bytes=size_bytes,
                storage_key=storage_key(org_id, file_id),
                status=FileStatus.UPLOADING,
                upload_expires_at=expires,
            )
        )
        form = await self._call(
            storage.presigned_post,
            upload_key(org_id, file_id),
            max_bytes=size_bytes,
            content_type=kind.content_type,
            expires_seconds=self._settings.files_upload_minutes * 60,
        )
        await self._db.commit()
        return UploadStarted(
            file=file_read(file, caller.user, caller),
            upload=UploadForm(url=form.url, fields=form.fields, expires_at=expires),
        )

    async def complete(self, caller: Caller, file_id: uuid.UUID) -> UploadCompleted:
        """The browser finished uploading: check the stored file."""
        caller.require(Permission.FILES_WRITE)
        storage = self._require_storage()
        org_id = caller.organization.id
        file = await self._files.get(file_id, organization_id=org_id, lock=True)
        if file is None:
            raise NotFoundError("This file does not exist.")
        if file.status is not FileStatus.UPLOADING:
            raise ConflictError("This upload was already completed.")
        staged = upload_key(org_id, file.id)
        if await self._call(storage.head, staged) is None:
            if file.upload_expires_at <= utcnow():
                await self._reject(file, "The upload link expired before the file arrived.")
                raise FileRejectedError("The upload took too long. Upload the file again.")
            raise ConflictError("The file has not arrived yet. Upload it, then try again.")
        kind = file_types.type_for_name(file.filename)
        assert kind is not None
        # Copy first, then check the copy: the browser can't change the final key.
        await self._call(storage.copy, staged, file.storage_key, kind.content_type)
        await self._delete_quietly(staged)
        info = await self._call(storage.head, file.storage_key)
        head = await self._call(storage.read_start, file.storage_key, file_types.SNIFF_BYTES)
        problem = None
        if info is None or info.size > file.size_bytes:
            problem = "The file is bigger than announced."
        elif not file_types.matches(kind, head):
            problem = f"The file is not a real {kind.label}, so it was not accepted."
        if problem or info is None:
            problem = problem or "The file could not be read."
            await self._call(storage.delete, file.storage_key)
            await self._reject(file, problem)
            raise FileRejectedError(problem)
        file.size_bytes = info.size  # the real size counts for the plan
        file.completed_at = utcnow()
        file.status = FileStatus.SCANNING if self._scan else FileStatus.READY
        await self._audit.record(
            AuditAction.FILE_UPLOADED,
            organization_id=org_id,
            actor_user_id=caller.user_id,
            actor_api_key_id=caller.api_key_id,
            target_type="file",
            target_id=file.id,
            details={"filename": file.filename, "size_bytes": file.size_bytes},
        )
        await self._db.commit()
        job_id = None
        if self._scan:
            try:
                job = await self._jobs.enqueue(
                    "file_scan",
                    {"file_id": str(file.id)},
                    organization_id=org_id,
                    created_by_id=caller.user_id,
                )
            except Exception:
                # No scan will ever run: don't leave the file "scanning" (and counted) forever.
                logger.exception("file_scan_not_started", file_id=str(file.id))
                await self._delete_quietly(file.storage_key)
                await self._reject(file, "The virus check could not start. Upload it again.")
                raise ServiceUnavailableError(
                    "The virus check could not start. Upload the file again in a minute."
                ) from None
            job_id = job.id
        logger.info("file_uploaded", file_id=str(file.id), size=file.size_bytes)
        return UploadCompleted(file=file_read(file, caller.user, caller), job_id=job_id)

    async def _delete_quietly(self, key: str) -> None:
        """Delete an object; if the storage refuses, the nightly clean-up tries again."""
        try:
            await asyncio.to_thread(self._require_storage().delete, key)
        except StorageError as exc:
            logger.warning("storage_delete_failed", key=key, error=str(exc))

    async def _reject(self, file: StoredFile, message: str) -> None:
        file.status = FileStatus.REJECTED
        file.status_message = message[:300]
        await self._db.commit()
        logger.info("file_rejected", file_id=str(file.id), reason=message)

    async def download_link(self, caller: Caller, file_id: uuid.UUID) -> DownloadLink:
        """A short-lived link that downloads the file (only ready files)."""
        caller.require(Permission.FILES_READ)
        storage = self._require_storage()
        file = await self._files.get(file_id, organization_id=caller.organization.id)
        if file is None or file.status is FileStatus.REJECTED:
            raise NotFoundError("This file does not exist.")
        if file.status is not FileStatus.READY:
            raise ConflictError("This file is still being checked. Try again in a moment.")
        seconds = self._settings.files_download_seconds
        url = await self._call(
            storage.presigned_get,
            file.storage_key,
            filename=file.filename,
            content_type=file.content_type,
            expires_seconds=seconds,
        )
        return DownloadLink(url=url, expires_at=utcnow() + timedelta(seconds=seconds))

    async def delete(self, caller: Caller, file_id: uuid.UUID) -> None:
        """Delete the stored bytes, then the row."""
        caller.require(Permission.FILES_WRITE)
        storage = self._require_storage()
        file = await self._files.get(file_id, organization_id=caller.organization.id, lock=True)
        if file is None or file.status is FileStatus.REJECTED:
            raise NotFoundError("This file does not exist.")
        if not can_delete(caller, file):
            raise PermissionDeniedError(
                "Only owners, admins and the person who uploaded a file can delete it."
            )
        if file.status is FileStatus.UPLOADING and file.upload_expires_at > utcnow():
            # Its upload form still works: deleting now would let bytes arrive uncounted.
            raise ConflictError(
                "This file is still uploading. If the upload failed, it is removed "
                "automatically within a day."
            )
        await self._call(storage.delete, file.storage_key)
        await self._audit.record(
            AuditAction.FILE_DELETED,
            organization_id=caller.organization.id,
            actor_user_id=caller.user_id,
            target_type="file",
            target_id=file.id,
            details={"filename": file.filename, "size_bytes": file.size_bytes},
        )
        await self._files.delete(file)
        await self._db.commit()
