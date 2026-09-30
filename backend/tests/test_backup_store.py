"""The backup store (deploy/backup.sh) against a local S3 API (moto). No Docker, no internet."""

import io
import socket
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest

from app.scripts.backup_store import KEEP_NEWEST, BackupSettings, BackupStore


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def s3_url() -> Iterator[str]:
    from moto.server import ThreadedMotoServer

    port = _free_port()
    server = ThreadedMotoServer(ip_address="127.0.0.1", port=port, verbose=False)
    server.start()
    yield f"http://127.0.0.1:{port}"
    server.stop()


@pytest.fixture
def store(s3_url: str) -> BackupStore:
    settings = BackupSettings(
        endpoint=s3_url,
        region="us-east-1",
        bucket=f"backups-{_free_port()}",
        access_key="k",
        secret_key="s",  # type: ignore[arg-type,unused-ignore]
    )
    s = BackupStore(settings)
    s._client.create_bucket(Bucket=settings.bucket)
    return s


def test_upload_download_roundtrip(store: BackupStore) -> None:
    data = b"\x00binary dump\xff" * 1000
    store.upload("db-a.dump.enc", io.BytesIO(data))
    out = io.BytesIO()
    store.download("db-a.dump.enc", out)
    assert out.getvalue() == data


def test_list_is_newest_first(store: BackupStore) -> None:
    store.upload("db-1.dump.enc", io.BytesIO(b"1"))
    store.upload("db-2.dump.enc", io.BytesIO(b"22"))
    items = store.list_backups()
    assert {name for name, _t, _s in items} == {"db-1.dump.enc", "db-2.dump.enc"}
    # S3 timestamps have a resolution of one second, so only the ORDER is checked.
    times = [uploaded for _n, uploaded, _s in items]
    assert times == sorted(times, reverse=True)


@pytest.mark.parametrize("bad", ["../x", "a/b", "", "x", "-rf", "a b", "a" * 200])
def test_bad_names_are_refused(store: BackupStore, bad: str) -> None:
    with pytest.raises(ValueError):
        store.upload(bad, io.BytesIO(b"x"))


def test_prune_deletes_old_but_keeps_newest(store: BackupStore) -> None:
    for i in range(KEEP_NEWEST + 3):
        store.upload(f"db-{i}.dump.enc", io.BytesIO(b"x"))
    # Pretend it is 30 days later: everything is "old", yet the newest few must stay.
    later = datetime.now(UTC) + timedelta(days=30)
    deleted = store.prune(keep_days=14, now=later)
    assert len(deleted) == 3
    assert len(store.list_backups()) == KEEP_NEWEST


def test_prune_keeps_recent(store: BackupStore) -> None:
    for i in range(KEEP_NEWEST + 2):
        store.upload(f"db-{i}.dump.enc", io.BytesIO(b"x"))
    assert store.prune(keep_days=14) == []


def test_missing_settings_stop_with_a_clear_message() -> None:
    with pytest.raises(SystemExit, match="BACKUP_S3_ENDPOINT"):
        BackupStore(BackupSettings(endpoint="", bucket="", access_key=""))


def test_size_and_delete(store: BackupStore) -> None:
    store.upload("db-size.dump.enc", io.BytesIO(b"x" * 1234))
    assert store.size("db-size.dump.enc") == 1234
    store.delete("db-size.dump.enc")
    assert store.size("db-size.dump.enc") is None
