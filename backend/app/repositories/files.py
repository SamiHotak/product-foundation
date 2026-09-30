"""File queries. Every API query takes the organization id (tenant isolation)."""

import uuid
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models.file import FileStatus, StoredFile
from app.models.user import User


class FileRepository:
    """Async file queries for the API."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, file: StoredFile) -> StoredFile:
        """Insert a file row."""
        self._session.add(file)
        await self._session.flush()
        return file

    async def get(
        self, file_id: uuid.UUID, *, organization_id: uuid.UUID, lock: bool = False
    ) -> StoredFile | None:
        """One file of this workspace (other workspaces' files "don't exist")."""
        query = select(StoredFile).where(
            StoredFile.id == file_id, StoredFile.organization_id == organization_id
        )
        if lock:
            query = query.with_for_update()
        found: StoredFile | None = await self._session.scalar(
            query.execution_options(populate_existing=True)
        )
        return found

    async def list(
        self, organization_id: uuid.UUID, *, limit: int
    ) -> list[tuple[StoredFile, User | None]]:
        """Files that finished uploading (ready or being scanned), newest first."""
        rows = await self._session.execute(
            select(StoredFile, User)
            .outerjoin(User, User.id == StoredFile.uploaded_by_id)
            .where(
                StoredFile.organization_id == organization_id,
                StoredFile.status.in_([FileStatus.READY, FileStatus.SCANNING]),
            )
            .order_by(StoredFile.created_at.desc(), StoredFile.id)
            .limit(limit)
        )
        return [(f, u) for f, u in rows.tuples()]

    async def delete(self, file: StoredFile) -> None:
        """Remove the row (the caller deleted the stored bytes first)."""
        await self._session.delete(file)
        await self._session.flush()


class SyncFileRepository:
    """Sync file queries for workers (virus scan, clean-up, seed data)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_for_update(self, file_id: uuid.UUID) -> StoredFile | None:
        """One file, locked until commit."""
        return self._session.get(StoredFile, file_id, with_for_update=True, populate_existing=True)

    def abandoned_uploads(self, before: datetime, limit: int = 500) -> list[StoredFile]:
        """Uploads nobody completed before their link expired (plus some margin)."""
        return list(
            self._session.scalars(
                select(StoredFile)
                .where(
                    StoredFile.status == FileStatus.UPLOADING,
                    StoredFile.upload_expires_at < before,
                )
                .limit(limit)
            )
        )

    def delete_row(self, file_id: uuid.UUID) -> None:
        """Remove one row."""
        self._session.execute(delete(StoredFile).where(StoredFile.id == file_id))
