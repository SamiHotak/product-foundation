"""Worker-side file work: the virus scan after an upload, and removing abandoned uploads."""

import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime, timedelta
from enum import StrEnum

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.session import sync_session
from app.models.file import FileStatus
from app.repositories.files import SyncFileRepository
from app.services.storage import UPLOADS_ROOT, ObjectStorage, StorageError, upload_prefix
from app.services.virus_scan import VirusScanner

logger = get_logger(__name__)

SessionFactory = Callable[[], AbstractContextManager[Session]]

# Uploads are removed this long after their upload link expired.
ABANDONED_AFTER = timedelta(hours=1)
# Staged uploads (see app/services/storage.py) are deleted when they are this old.
STAGED_MAX_AGE = timedelta(days=1)


class FileGone(Exception):  # noqa: N818 - reads well at the call site
    """The file row was deleted (or is no longer waiting for a scan)."""


class ScanOutcome(StrEnum):
    """What the scan decided."""

    CLEAN = "clean"
    INFECTED = "infected"
    GAVE_UP = "gave_up"  # the scanner stayed unreachable; the file was not accepted


def scan_file(
    file_id: str,
    storage: ObjectStorage,
    scanner: VirusScanner,
    *,
    give_up: bool = False,
    open_session: SessionFactory = sync_session,
) -> ScanOutcome:
    """Scan one file and set its status. Raises ScannerUnavailableError / StorageError
    for temporary problems (the job retries), unless `give_up` (the last try)."""
    with open_session() as session:
        file = SyncFileRepository(session).get_for_update(uuid.UUID(file_id))
        if file is None or file.status is not FileStatus.SCANNING:
            raise FileGone(file_id)
        key = file.storage_key
    try:
        result = scanner.scan(storage.iter_chunks(key))
    except Exception:
        if not give_up:
            raise
        _finish(file_id, FileStatus.REJECTED, "The file could not be scanned.", open_session)
        _delete_quietly(storage, key)
        return ScanOutcome.GAVE_UP
    if result.clean:
        _finish(file_id, FileStatus.READY, None, open_session)
        return ScanOutcome.CLEAN
    logger.warning("file_infected", file_id=file_id, signature=result.signature)
    _delete_quietly(storage, key)
    _finish(file_id, FileStatus.REJECTED, "A virus was found in this file.", open_session)
    return ScanOutcome.INFECTED


def _finish(
    file_id: str, status: FileStatus, message: str | None, open_session: SessionFactory
) -> None:
    with open_session() as session:
        file = SyncFileRepository(session).get_for_update(uuid.UUID(file_id))
        if file is not None:
            file.status = status
            file.status_message = message


def _delete_quietly(storage: ObjectStorage, key: str) -> None:
    try:
        storage.delete(key)
    except StorageError as exc:  # the nightly clean-up can't find it: log for a human
        logger.error("file_delete_failed", key=key, error=str(exc))


def remove_abandoned_uploads(
    open_session: SessionFactory, storage: ObjectStorage, now: datetime
) -> int:
    """Delete uploads nobody completed (the bytes, if any arrived, then the row)."""
    removed = 0
    with open_session() as session:
        stale = [
            (f.id, f.storage_key, f"{upload_prefix(f.organization_id)}{f.id}")
            for f in SyncFileRepository(session).abandoned_uploads(now - ABANDONED_AFTER)
        ]
    for file_id, key, staged in stale:
        try:
            storage.delete(staged)
            storage.delete(key)
        except StorageError as exc:
            logger.warning("abandoned_upload_not_deleted", file_id=str(file_id), error=str(exc))
            continue  # try again tomorrow; the row keeps counting until then
        with open_session() as session:
            SyncFileRepository(session).delete_row(file_id)
        removed += 1
    return removed


def remove_stale_staged(storage: ObjectStorage, now: datetime) -> int:
    """Delete staged uploads older than a day (completed ones were copied already)."""
    try:
        return storage.delete_older_than(UPLOADS_ROOT, now - STAGED_MAX_AGE)
    except StorageError as exc:
        logger.warning("staged_uploads_not_deleted", error=str(exc))
        return 0
