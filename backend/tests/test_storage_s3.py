"""The real S3 client (boto3) against a local S3 API (moto server): signed upload forms,
download links, reading, deleting and the bucket setup. No Docker, no internet."""

import socket
import urllib.parse
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.core.config import Environment, Settings
from app.services.storage import S3Storage, StorageError, attachment_header, storage_for


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


def _settings(s3_url: str, **changes: object) -> Settings:
    values: dict[str, object] = {
        "environment": Environment.TEST,
        "s3_endpoint": s3_url,
        "s3_access_key": "test-key",
        "s3_secret_key": "test-secret",
        "s3_bucket": "foundation-test",
        **changes,
    }
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


@pytest.fixture
def storage(s3_url: str) -> S3Storage:
    store = S3Storage(_settings(s3_url))
    store.ensure_bucket(cors_origins=["http://localhost:3000"])
    return store


def test_signed_upload_form_download_link_and_reading(storage: S3Storage) -> None:
    key = "orgs/11111111-2222-3333-4444-555555555555/files/abc"
    form = storage.presigned_post(key, max_bytes=100, content_type="text/csv", expires_seconds=60)
    assert form.fields["key"] == key and form.fields["Content-Type"] == "text/csv"
    res = httpx.post(form.url, data=form.fields, files={"file": ("x.csv", b"a,b\n1,2\n")})
    assert res.status_code in (200, 204), res.text

    info = storage.head(key)
    assert info is not None and info.size == 8 and info.content_type == "text/csv"
    assert storage.read_start(key, 3) == b"a,b"
    assert b"".join(storage.iter_chunks(key, chunk_size=3)) == b"a,b\n1,2\n"

    url = storage.presigned_get(
        key, filename="Preisliste März.csv", content_type="text/csv", expires_seconds=60
    )
    res = httpx.get(url)
    assert res.status_code == 200 and res.content == b"a,b\n1,2\n"
    disposition = res.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert urllib.parse.quote("Preisliste März.csv") in disposition

    storage.delete(key)
    assert storage.head(key) is None
    storage.delete(key)  # deleting twice is fine


def test_delete_prefix_removes_one_workspace_only(storage: S3Storage) -> None:
    a, b = "orgs/aaaaaaaa-0000/", "orgs/bbbbbbbb-0000/"
    for i in range(3):
        storage.put(f"{a}files/{i}", b"x", "text/plain")
    storage.put(f"{b}files/0", b"y", "text/plain")
    assert storage.delete_prefix(a) == 3
    assert storage.head(f"{a}files/0") is None
    assert storage.head(f"{b}files/0") is not None
    with pytest.raises(ValueError, match="short"):
        storage.delete_prefix("orgs")


def test_copy_and_delete_old_staged_uploads(storage: S3Storage) -> None:
    staged, final = "uploads/cccccccc-0000/1", "orgs/cccccccc-0000/files/1"
    storage.put(staged, b"%PDF-1.4\n", "application/octet-stream")
    storage.copy(staged, final, "application/pdf")
    info = storage.head(final)
    assert info is not None and info.size == 9 and info.content_type == "application/pdf"
    now = datetime.now(UTC)
    assert storage.delete_older_than("uploads/", now - timedelta(days=1)) == 0
    assert storage.delete_older_than("uploads/", now + timedelta(minutes=5)) == 1
    assert storage.head(staged) is None and storage.head(final) is not None
    with pytest.raises(StorageError):
        storage.copy("uploads/missing", final, "text/plain")


def test_public_url_replaces_the_endpoint(s3_url: str) -> None:
    store = S3Storage(_settings(s3_url, s3_public_url="/storage"))
    form = store.presigned_post("k/1", max_bytes=5, content_type="text/plain", expires_seconds=60)
    assert form.url == "/storage/foundation-test"
    url = store.presigned_get(
        "k/1", filename="a.txt", content_type="text/plain", expires_seconds=60
    )
    assert url.startswith("/storage/foundation-test/k/1?")


def test_errors_become_storage_errors() -> None:
    store = S3Storage(_settings("http://127.0.0.1:9", s3_bucket="nope"))  # nothing listens
    with pytest.raises(StorageError):
        store.check()
    with pytest.raises(StorageError):
        store.head("a")


def test_storage_for_is_cached_and_off_without_endpoint(s3_url: str) -> None:
    settings = _settings(s3_url)
    assert storage_for(settings) is storage_for(settings.model_copy())
    assert storage_for(Settings(_env_file=None, environment=Environment.TEST)) is None


def test_attachment_header_is_safe_for_any_name() -> None:
    assert attachment_header("report.pdf") == (
        "attachment; filename=\"report.pdf\"; filename*=UTF-8''report.pdf"
    )
    header = attachment_header('evil".pdf')
    assert 'filename="evil.pdf"' in header
    assert attachment_header("日本.txt").startswith('attachment; filename=".txt"')
    assert attachment_header("日本").startswith('attachment; filename="file"')
