"""S3-compatible object storage (SeaweedFS locally, Hetzner Object Storage in production).

The browser uploads and downloads DIRECTLY to/from the storage with short-lived signed
links, so big files never pass through our API:

- upload:   a signed POST form for a STAGING key (`uploads/<workspace>/<file>`). The
            storage itself refuses files that are bigger than allowed
            (`content-length-range`) or have another content type. The form stays valid
            for a few minutes, so the browser could send again later: that is why the
            server copies the staged file to its final key (`orgs/<workspace>/files/<file>`,
            never writable by a browser) BEFORE it checks it. Old staging objects are
            removed every night (and by a bucket lifecycle rule where the storage has one).
- download: a signed GET link that forces "download" (never shown inline in the browser).

`S3_PUBLIC_URL` is where browsers reach the storage. Locally it is "/storage": the Next.js
server forwards /storage/... to S3_ENDPOINT and sends S3_ENDPOINT's host, so the signature
still matches. In production leave it empty: browsers go straight to Hetzner (the bucket
needs a CORS rule for your domain; `make storage-setup` sets it).

Methods are blocking (boto3). Async code calls them with `asyncio.to_thread`.
"""

import time
import urllib.parse
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import Settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class StorageError(Exception):
    """The storage could not be reached or refused the request."""


@dataclass(frozen=True)
class PresignedPost:
    """What the browser needs to upload one file: POST `fields` + the file to `url`."""

    url: str
    fields: dict[str, str]


@dataclass(frozen=True)
class ObjectInfo:
    """What the storage knows about a stored object."""

    size: int
    content_type: str | None


class ObjectStorage(Protocol):
    """What the app needs from a storage (tests use an in-memory fake)."""

    def presigned_post(
        self, key: str, *, max_bytes: int, content_type: str, expires_seconds: int
    ) -> PresignedPost:
        """A signed upload form for exactly this key."""
        ...

    def presigned_get(
        self, key: str, *, filename: str, content_type: str, expires_seconds: int
    ) -> str:
        """A signed link that downloads the object as an attachment."""
        ...

    def head(self, key: str) -> ObjectInfo | None:
        """Size and type of an object, or None when it does not exist."""
        ...

    def read_start(self, key: str, length: int) -> bytes:
        """The first `length` bytes (to check what the file really is)."""
        ...

    def iter_chunks(self, key: str, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
        """The whole object, piece by piece (virus scan)."""
        ...

    def put(self, key: str, data: bytes, content_type: str) -> None:
        """Store small data directly (seed data, tests)."""
        ...

    def copy(self, source: str, target: str, content_type: str) -> None:
        """Copy one object inside the bucket (server side, no download)."""
        ...

    def delete_older_than(self, prefix: str, before: datetime) -> int:
        """Delete objects under `prefix` last changed before `before`. Returns how many."""
        ...

    def delete(self, key: str) -> None:
        """Delete one object (no error if it is already gone)."""
        ...

    def delete_prefix(self, prefix: str) -> int:
        """Delete every object whose key starts with `prefix`. Returns how many."""
        ...

    def check(self) -> None:
        """Raise StorageError unless the bucket can be reached (health check)."""
        ...


def attachment_header(filename: str) -> str:
    """Content-Disposition that downloads with the original name (any language, RFC 6266)."""
    ascii_name = filename.encode("ascii", "ignore").decode() or "file"
    ascii_name = ascii_name.replace('"', "").replace("\\", "")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{urllib.parse.quote(filename)}"


# Browsers upload here first; nothing under it is ever served or trusted.
UPLOADS_ROOT = "uploads/"


def org_prefix(organization_id: object) -> str:
    """Every checked object of one workspace starts with this."""
    return f"orgs/{organization_id}/"


def upload_prefix(organization_id: object) -> str:
    """Every staged (not yet checked) upload of one workspace starts with this."""
    return f"{UPLOADS_ROOT}{organization_id}/"


def org_prefixes(organization_id: object) -> tuple[str, str]:
    """All prefixes of one workspace (deleting a workspace deletes both)."""
    return org_prefix(organization_id), upload_prefix(organization_id)


class S3Storage:
    """ObjectStorage on any S3-compatible service (boto3)."""

    def __init__(self, settings: Settings) -> None:
        assert settings.s3_secret_key is not None
        self._bucket = settings.s3_bucket
        self._endpoint = settings.s3_endpoint
        self._public = settings.s3_public_url or settings.s3_endpoint
        self._client: Any = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
            config=Config(
                signature_version="s3v4",
                # Path style (endpoint/bucket/key) works with every S3 service we use.
                s3={"addressing_style": "path"},
                connect_timeout=3,
                read_timeout=30,
                retries={"max_attempts": 3, "mode": "standard"},
                # Only send checksums the service asks for (some S3 services reject the rest).
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
            ),
        )

    def _to_public(self, url: str) -> str:
        if self._public != self._endpoint and url.startswith(self._endpoint):
            return self._public + url[len(self._endpoint) :]
        return url

    def presigned_post(
        self, key: str, *, max_bytes: int, content_type: str, expires_seconds: int
    ) -> PresignedPost:
        """A signed upload form. The storage checks size and content type itself."""
        post = self._client.generate_presigned_post(
            Bucket=self._bucket,
            Key=key,
            Fields={"Content-Type": content_type},
            Conditions=[
                ["content-length-range", 1, max_bytes],
                {"Content-Type": content_type},
            ],
            ExpiresIn=expires_seconds,
        )
        return PresignedPost(url=self._to_public(post["url"]), fields=dict(post["fields"]))

    def presigned_get(
        self, key: str, *, filename: str, content_type: str, expires_seconds: int
    ) -> str:
        """A signed download link. Always an attachment, never displayed inline."""
        url: str = self._client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self._bucket,
                "Key": key,
                "ResponseContentDisposition": attachment_header(filename),
                "ResponseContentType": content_type,
            },
            ExpiresIn=expires_seconds,
        )
        return self._to_public(url)

    def head(self, key: str) -> ObjectInfo | None:
        """Size and type, or None if missing."""
        try:
            found = self._client.head_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise StorageError(f"head failed: {exc}") from exc
        except BotoCoreError as exc:
            raise StorageError(f"head failed: {exc}") from exc
        return ObjectInfo(size=int(found["ContentLength"]), content_type=found.get("ContentType"))

    def read_start(self, key: str, length: int) -> bytes:
        """The first bytes of an object."""
        try:
            found = self._client.get_object(
                Bucket=self._bucket, Key=key, Range=f"bytes=0-{length - 1}"
            )
            data: bytes = found["Body"].read(length)
        except (ClientError, BotoCoreError) as exc:
            raise StorageError(f"read failed: {exc}") from exc
        return data

    def iter_chunks(self, key: str, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
        """Stream the object."""
        try:
            body = self._client.get_object(Bucket=self._bucket, Key=key)["Body"]
            yield from body.iter_chunks(chunk_size)
        except (ClientError, BotoCoreError) as exc:
            raise StorageError(f"read failed: {exc}") from exc

    def put(self, key: str, data: bytes, content_type: str) -> None:
        """Upload small data from the server."""
        try:
            self._client.put_object(
                Bucket=self._bucket, Key=key, Body=data, ContentType=content_type
            )
        except (ClientError, BotoCoreError) as exc:
            raise StorageError(f"put failed: {exc}") from exc

    def copy(self, source: str, target: str, content_type: str) -> None:
        """Server-side copy (the bytes never leave the storage)."""
        try:
            self._client.copy_object(
                Bucket=self._bucket,
                Key=target,
                CopySource={"Bucket": self._bucket, "Key": source},
                MetadataDirective="REPLACE",
                ContentType=content_type,
            )
        except (ClientError, BotoCoreError) as exc:
            raise StorageError(f"copy failed: {exc}") from exc

    def delete_older_than(self, prefix: str, before: datetime) -> int:
        """Delete stale objects under a prefix (old staged uploads)."""
        if not prefix.endswith("/"):
            raise ValueError("Refusing an unterminated prefix.")
        deleted = 0
        try:
            paginator = self._client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
                for item in page.get("Contents", []):
                    if item["LastModified"] < before:
                        self._client.delete_object(Bucket=self._bucket, Key=item["Key"])
                        deleted += 1
        except (ClientError, BotoCoreError) as exc:
            raise StorageError(f"delete failed: {exc}") from exc
        return deleted

    def delete(self, key: str) -> None:
        """Delete one object."""
        try:
            self._client.delete_object(Bucket=self._bucket, Key=key)
        except (ClientError, BotoCoreError) as exc:
            raise StorageError(f"delete failed: {exc}") from exc

    def delete_prefix(self, prefix: str) -> int:
        """Delete everything under a prefix (a whole workspace)."""
        if not prefix.endswith("/") or len(prefix) < 10:
            raise ValueError("Refusing to delete a short or unterminated prefix.")
        deleted = 0
        try:
            paginator = self._client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
                keys = [{"Key": item["Key"]} for item in page.get("Contents", [])]
                # One by one: some S3 services don't support the batch delete call.
                for key in keys:
                    self._client.delete_object(Bucket=self._bucket, Key=key["Key"])
                deleted += len(keys)
        except (ClientError, BotoCoreError) as exc:
            raise StorageError(f"delete failed: {exc}") from exc
        return deleted

    def check(self) -> None:
        """HEAD the bucket."""
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except (ClientError, BotoCoreError) as exc:
            raise StorageError(f"bucket not reachable: {exc}") from exc

    def ensure_bucket(self, *, cors_origins: list[str], attempts: int = 20) -> bool:
        """Create the bucket if missing and allow browser uploads from our origins.

        Waits for the storage to start (Docker starts it together with the backend).
        Returns True if the bucket was created. Used by `make storage-setup` and dev start.
        """
        for attempt in range(1, attempts + 1):
            try:
                self._client.head_bucket(Bucket=self._bucket)
                created = False
                break
            except ClientError as exc:
                if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchBucket", "NotFound"}:
                    self._client.create_bucket(Bucket=self._bucket)
                    created = True
                    break
                raise
            except BotoCoreError:
                if attempt == attempts:
                    raise
                time.sleep(1)
        cors = {
            "CORSRules": [
                {
                    "AllowedOrigins": cors_origins,
                    "AllowedMethods": ["GET", "POST"],
                    "AllowedHeaders": ["*"],
                    "ExposeHeaders": ["ETag"],
                    "MaxAgeSeconds": 3600,
                }
            ]
        }
        try:
            self._client.put_bucket_cors(Bucket=self._bucket, CORSConfiguration=cors)
        except ClientError as exc:
            # Only direct browser uploads need it (not the local /storage proxy).
            logger.warning("storage_cors_not_set", error=str(exc))
        lifecycle = {
            "Rules": [
                {
                    "ID": "expire-staged-uploads",
                    "Filter": {"Prefix": UPLOADS_ROOT},
                    "Status": "Enabled",
                    "Expiration": {"Days": 1},
                }
            ]
        }
        try:
            self._client.put_bucket_lifecycle_configuration(
                Bucket=self._bucket, LifecycleConfiguration=lifecycle
            )
        except ClientError as exc:
            # Not every storage supports it; the nightly clean-up does the same job.
            logger.warning("storage_lifecycle_not_set", error=str(exc))
        return created


_clients: dict[tuple[str, ...], S3Storage] = {}


def storage_for(settings: Settings) -> ObjectStorage | None:
    """The configured storage, or None when files are switched off.

    One client per configuration (boto3 clients are thread-safe and slow to create).
    """
    if not settings.files_enabled:
        return None
    assert settings.s3_secret_key is not None
    key = (
        settings.s3_endpoint,
        settings.s3_public_url,
        settings.s3_region,
        settings.s3_bucket,
        settings.s3_access_key,
        settings.s3_secret_key.get_secret_value(),
    )
    if key not in _clients:
        _clients[key] = S3Storage(settings)
    return _clients[key]
