"""Files of the active workspace. Part of the public REST API (scopes files:read/write).

Upload in three steps: POST /files/uploads -> send the file to `upload.url` as a form
(every field of `upload.fields`, then `file`) -> POST /files/{id}/complete.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Response, status

from app.core.permissions import Permission
from app.routers.deps import Files, allow_api_keys
from app.schemas.errors import error_responses
from app.schemas.files import DownloadLink, FileList, UploadCompleted, UploadStart, UploadStarted
from app.services.organizations import Caller

router = APIRouter(prefix="/files", tags=["files"])

CanRead = Annotated[Caller, allow_api_keys(Permission.FILES_READ)]
CanWrite = Annotated[Caller, allow_api_keys(Permission.FILES_WRITE)]


@router.get("", response_model=FileList, responses=error_responses(401, 403, 429), summary="Files")
async def list_files(caller: CanRead, files: Files) -> FileList:
    """Files of the workspace, newest first, plus the upload rules."""
    return await files.list_files(caller)


@router.post(
    "/uploads",
    response_model=UploadStarted,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(400, 401, 402, 403, 429, 503),
    summary="Start an upload",
)
async def start_upload(data: UploadStart, caller: CanWrite, files: Files) -> UploadStarted:
    """Checks name, type, size and the plan's storage; returns a signed upload form."""
    return await files.start_upload(caller, data.filename, data.size_bytes)


@router.post(
    "/{file_id}/complete",
    response_model=UploadCompleted,
    responses=error_responses(400, 401, 403, 404, 409, 429, 503),
    summary="Finish an upload",
)
async def complete_upload(file_id: uuid.UUID, caller: CanWrite, files: Files) -> UploadCompleted:
    """Checks the stored file. 400 `file_rejected` if it is not what its name says."""
    return await files.complete(caller, file_id)


@router.post(
    "/{file_id}/download",
    response_model=DownloadLink,
    responses=error_responses(401, 403, 404, 409, 429, 503),
    summary="Get a download link",
)
async def download_link(file_id: uuid.UUID, caller: CanRead, files: Files) -> DownloadLink:
    """A link that works for a few minutes. POST, so links never end up in logs or caches."""
    return await files.download_link(caller, file_id)


@router.delete(
    "/{file_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=error_responses(401, 403, 404, 429, 503),
    summary="Delete a file",
)
async def delete_file(file_id: uuid.UUID, caller: CanWrite, files: Files) -> Response:
    """Deletes the stored file immediately. Owners/admins: any file; members: their own."""
    await files.delete(caller, file_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
