"""Store database backups in a SEPARATE S3 bucket (used by deploy/backup.sh).

    python -m app.scripts.backup_store upload  db-2026-09-30T0230Z.dump.enc   (reads stdin)
    python -m app.scripts.backup_store download db-....dump.enc               (writes stdout)
    python -m app.scripts.backup_store latest                                 (prints newest name)
    python -m app.scripts.backup_store size NAME                              (prints bytes)
    python -m app.scripts.backup_store delete NAME
    python -m app.scripts.backup_store list
    python -m app.scripts.backup_store prune --keep-days 14

Why a separate bucket and separate keys: if the app's file-storage keys leak, backups stay safe
(and the other way round). The dumps are also encrypted on the server before they get here.

Settings (environment): BACKUP_S3_ENDPOINT, BACKUP_S3_REGION, BACKUP_S3_BUCKET,
BACKUP_S3_ACCESS_KEY, BACKUP_S3_SECRET_KEY.
"""

import argparse
import re
import sys
from datetime import UTC, datetime, timedelta
from typing import Any, BinaryIO

import boto3
from botocore.config import Config
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PREFIX = "backups/"
# Names come from backup.sh; never accept anything else (keys are built from them).
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,120}$")
# Pruning never deletes the newest backups, whatever their age (a stopped clock or a broken
# backup job must not make the last good copies disappear).
KEEP_NEWEST = 3


class BackupSettings(BaseSettings):
    """Where backups are stored."""

    model_config = SettingsConfigDict(env_prefix="BACKUP_S3_", extra="ignore")

    endpoint: str = ""
    region: str = "fsn1"
    bucket: str = ""
    access_key: str = ""
    secret_key: SecretStr | None = None

    def check(self) -> None:
        """Fail early with a clear message when something is missing."""
        missing = [
            name
            for name, value in (
                ("BACKUP_S3_ENDPOINT", self.endpoint),
                ("BACKUP_S3_BUCKET", self.bucket),
                ("BACKUP_S3_ACCESS_KEY", self.access_key),
                ("BACKUP_S3_SECRET_KEY", self.secret_key and self.secret_key.get_secret_value()),
            )
            if not value
        ]
        if missing:
            raise SystemExit(f"Missing settings: {', '.join(missing)}")


class BackupStore:
    """Upload, download, list and prune backup files."""

    def __init__(self, settings: BackupSettings) -> None:
        settings.check()
        assert settings.secret_key is not None
        self._bucket = settings.bucket
        self._client: Any = boto3.client(
            "s3",
            endpoint_url=settings.endpoint,
            region_name=settings.region,
            aws_access_key_id=settings.access_key,
            aws_secret_access_key=settings.secret_key.get_secret_value(),
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
                connect_timeout=5,
                read_timeout=60,
                retries={"max_attempts": 5, "mode": "standard"},
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
            ),
        )

    @staticmethod
    def key(name: str) -> str:
        """The object key of a backup name (validated)."""
        if not NAME_RE.fullmatch(name):
            raise ValueError(f"Bad backup name: {name!r}")
        return PREFIX + name

    def upload(self, name: str, stream: BinaryIO) -> None:
        """Stream a file in (multipart, so a big dump never sits fully in memory)."""
        self._client.upload_fileobj(stream, self._bucket, self.key(name))

    def download(self, name: str, out: BinaryIO) -> None:
        """Stream a backup out."""
        self._client.download_fileobj(self._bucket, self.key(name), out)

    def list_backups(self) -> list[tuple[str, datetime, int]]:
        """(name, uploaded at, bytes), newest first."""
        items: list[tuple[str, datetime, int]] = []
        token: str | None = None
        while True:
            args: dict[str, Any] = {"Bucket": self._bucket, "Prefix": PREFIX}
            if token:
                args["ContinuationToken"] = token
            page = self._client.list_objects_v2(**args)
            for obj in page.get("Contents", []):
                name = obj["Key"][len(PREFIX) :]
                if NAME_RE.fullmatch(name):
                    items.append((name, obj["LastModified"], int(obj["Size"])))
            if not page.get("IsTruncated"):
                break
            token = page["NextContinuationToken"]
        return sorted(items, key=lambda item: item[1], reverse=True)

    def size(self, name: str) -> int | None:
        """Size in bytes, or None if the backup does not exist."""
        for item_name, _uploaded, size in self.list_backups():
            if item_name == name:
                return size
        return None

    def delete(self, name: str) -> None:
        """Delete one backup (used to remove a half-written upload)."""
        self._client.delete_object(Bucket=self._bucket, Key=self.key(name))

    def prune(self, *, keep_days: int, now: datetime | None = None) -> list[str]:
        """Delete backups older than `keep_days`, but always keep the newest few."""
        cutoff = (now or datetime.now(UTC)) - timedelta(days=keep_days)
        deleted: list[str] = []
        for name, uploaded, _size in self.list_backups()[KEEP_NEWEST:]:
            if uploaded < cutoff:
                self._client.delete_object(Bucket=self._bucket, Key=self.key(name))
                deleted.append(name)
        return deleted


def main(argv: list[str] | None = None) -> int:
    """Command line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0] if __doc__ else "")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("upload", "download", "size", "delete"):
        sub.add_parser(command).add_argument("name")
    sub.add_parser("latest")
    sub.add_parser("list")
    prune = sub.add_parser("prune")
    prune.add_argument("--keep-days", type=int, default=14)
    args = parser.parse_args(argv)

    store = BackupStore(BackupSettings())
    if args.command == "upload":
        store.upload(args.name, sys.stdin.buffer)
        print(f"Uploaded {args.name}", file=sys.stderr)
    elif args.command == "download":
        store.download(args.name, sys.stdout.buffer)
    elif args.command == "size":
        size = store.size(args.name)
        if size is None:
            print(f"{args.name} not found.", file=sys.stderr)
            return 1
        print(size)
    elif args.command == "delete":
        store.delete(args.name)
    elif args.command == "latest":
        items = store.list_backups()
        if not items:
            print("No backups found.", file=sys.stderr)
            return 1
        print(items[0][0])
    elif args.command == "list":
        for name, uploaded, size in store.list_backups():
            print(f"{uploaded:%Y-%m-%d %H:%M} UTC  {size / 1_048_576:8.1f} MB  {name}")
    elif args.command == "prune":
        if args.keep_days < 1:
            raise SystemExit("--keep-days must be at least 1")
        for name in store.prune(keep_days=args.keep_days):
            print(f"Deleted {name}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
