"""Unit tests (no database): file names and types, ClamAV protocol, storage settings,
and the session restrictions for the demo user and admins viewing as someone."""

import socket
import struct
import threading

import pytest

from app.core.config import Environment, Settings
from app.core.restrictions import (
    DemoReadOnlyError,
    ImpersonationBlockedError,
    check_session_restrictions,
)
from app.services import file_types
from app.services.virus_scan import ClamdScanner, ScannerUnavailableError, parse_reply, scanner_for


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("report.pdf", "report.pdf"),
        ("C:\\Users\\me\\Desktop\\report.pdf", "report.pdf"),
        ("../../etc/passwd", "passwd"),
        ("  lots   of   space  .txt ", "lots of space .txt"),
        ("bad\x00name\x1f.txt", "badname.txt"),
        ("...", ""),
        ("Ü" * 300 + ".pdf", "Ü" * 247 + ".pdf"),
    ],
)
def test_clean_filename(raw: str, clean: str) -> None:
    assert file_types.clean_filename(raw) == clean
    assert len(file_types.clean_filename(raw)) <= 255


def test_types_by_name_and_content() -> None:
    pdf = file_types.type_for_name("A.PDF")
    assert pdf is not None and pdf.content_type == "application/pdf"
    assert file_types.type_for_name("x.html") is None
    assert file_types.type_for_name("x.svg") is None
    assert file_types.type_for_name("x") is None
    assert file_types.matches(pdf, b"%PDF-1.7 ...")
    assert not file_types.matches(pdf, b"<html>")
    webp = file_types.type_for_name("a.webp")
    assert webp is not None
    assert file_types.matches(webp, b"RIFF\x00\x00\x00\x00WEBP")
    assert not file_types.matches(webp, b"RIFF\x00\x00\x00\x00WAVE")  # a .wav renamed
    text = file_types.type_for_name("a.txt")
    assert text is not None
    assert file_types.matches(text, "Grüße aus Mönchengladbach\n".encode())
    # A sample may end in the middle of a multi-byte character.
    assert file_types.matches(text, "ä".encode() * 10 + "ä".encode()[:1])
    assert not file_types.matches(text, b"MZ\x90\x00\x03")  # an .exe
    assert not file_types.matches(text, bytes(range(1, 32)) * 10)
    assert "pdf" in file_types.allowed_extensions()


def test_clamd_reply_parsing() -> None:
    assert parse_reply("stream: OK").clean
    found = parse_reply("stream: Win.Test.EICAR_HDB-1 FOUND")
    assert not found.clean and found.signature == "Win.Test.EICAR_HDB-1"
    with pytest.raises(ScannerUnavailableError):
        parse_reply("INSTREAM size limit exceeded. ERROR")


def _fake_clamd(reply: bytes) -> tuple[int, list[bytes]]:
    """A one-shot clamd that records what it got and answers `reply`."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    received: list[bytes] = []

    def serve() -> None:
        conn, _ = server.accept()
        with conn:
            assert conn.recv(10) == b"zINSTREAM\0"
            while True:
                size = struct.unpack(">I", conn.recv(4, socket.MSG_WAITALL))[0]
                if size == 0:
                    break
                received.append(conn.recv(size, socket.MSG_WAITALL))
            conn.sendall(reply)
        server.close()

    threading.Thread(target=serve, daemon=True).start()
    return int(server.getsockname()[1]), received


def test_clamd_scanner_streams_in_chunks() -> None:
    port, received = _fake_clamd(b"stream: OK\0")
    result = ClamdScanner("127.0.0.1", port, timeout=5).scan([b"a" * 70_000, b"b"])
    assert result.clean
    assert b"".join(received) == b"a" * 70_000 + b"b"
    assert max(len(r) for r in received) <= 64 * 1024


def test_clamd_unreachable() -> None:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    with pytest.raises(ScannerUnavailableError):
        ClamdScanner("127.0.0.1", port, timeout=1).scan([b"x"])
    base = Settings(_env_file=None, environment=Environment.TEST)
    assert scanner_for(base) is None
    assert scanner_for(base.model_copy(update={"clamav_host": "clamav"})) is not None


def _settings(**values: object) -> Settings:
    return Settings(_env_file=None, environment=Environment.TEST, **values)  # type: ignore[arg-type]


def test_storage_settings_are_checked() -> None:
    ok = _settings(s3_endpoint="http://s3:8333/", s3_access_key="a", s3_secret_key="b")
    assert ok.files_enabled and ok.s3_endpoint == "http://s3:8333"
    assert not _settings().files_enabled
    for bad, message in [
        ({"s3_endpoint": "s3:8333", "s3_access_key": "a", "s3_secret_key": "b"}, "https://"),
        ({"s3_endpoint": "http://s3"}, "S3_ACCESS_KEY"),
        (
            {
                "s3_endpoint": "http://s3",
                "s3_access_key": "a",
                "s3_secret_key": "b",
                "s3_bucket": "Bad_Name",
            },
            "S3_BUCKET",
        ),
        ({"s3_public_url": "storage"}, "S3_PUBLIC_URL"),
        ({"files_max_bytes": 10}, "FILES_MAX_BYTES"),
        ({"langfuse_public_key": "pk"}, "LANGFUSE_SECRET_KEY"),
    ]:
        assert isinstance(bad, dict)
        with pytest.raises(ValueError, match=message):
            _settings(**bad)
    with pytest.raises(ValueError, match="LLM_DEV_FAKE"):
        Settings(
            _env_file=None,
            environment=Environment.PRODUCTION,
            llm_dev_fake=True,
            secret_key="x" * 40,
        )


@pytest.mark.parametrize(
    ("method", "path", "allowed"),
    [
        ("GET", "/api/organizations/current/members", True),
        ("POST", "/api/jobs/example", True),
        ("POST", "/api/ai/summaries", True),
        ("POST", "/api/files/0b0f7f0e-8c1c-4d4e-9a8b-1c2d3e4f5a6b/download", True),
        ("POST", "/api/auth/logout", True),
        ("POST", "/api/organizations/current/invites", False),
        ("POST", "/api/files/uploads", False),
        ("DELETE", "/api/files/0b0f7f0e-8c1c-4d4e-9a8b-1c2d3e4f5a6b", False),
        ("PATCH", "/api/account/profile", False),
        ("POST", "/api/billing/checkout", False),
        ("POST", "/api/account/deletion", False),
    ],
)
def test_demo_user_is_read_mostly(method: str, path: str, allowed: bool) -> None:
    if allowed:
        check_session_restrictions(
            method, path, api_prefix="/api", is_demo=True, impersonating=False
        )
    else:
        with pytest.raises(DemoReadOnlyError):
            check_session_restrictions(
                method, path, api_prefix="/api", is_demo=True, impersonating=False
            )
    # Normal users are never restricted.
    check_session_restrictions(method, path, api_prefix="/api", is_demo=False, impersonating=False)


@pytest.mark.parametrize(
    ("method", "path", "blocked"),
    [
        ("PUT", "/api/account/password", True),
        ("POST", "/api/account/deletion", True),
        ("POST", "/api/billing/checkout", True),
        ("POST", "/api/organizations/current/api-keys", True),
        ("POST", "/api/organizations/current/invites", True),
        ("PATCH", "/api/organizations/current/members/0b0f7f0e-8c1c-4d4e-9a8b-1c2d3e4f5a6b", True),
        ("POST", "/api/organizations/current/leave", True),
        ("POST", "/api/organizations", True),
        ("PATCH", "/api/organizations/current", True),
        ("POST", "/api/files/uploads", True),
        ("GET", "/api/exports/abc/download", True),
        ("POST", "/somewhere-else", True),
        ("GET", "/api/organizations/current/members", False),
        ("POST", "/api/jobs/example", False),
        ("POST", "/api/auth/logout", False),
        ("POST", "/api/admin/impersonation/stop", False),
    ],
)
def test_admin_viewing_as_someone_may_only_read_and_try(
    method: str, path: str, blocked: bool
) -> None:
    if blocked:
        with pytest.raises(ImpersonationBlockedError):
            check_session_restrictions(
                method, path, api_prefix="/api", is_demo=False, impersonating=True
            )
    else:
        check_session_restrictions(
            method, path, api_prefix="/api", is_demo=False, impersonating=True
        )


def test_rules_follow_the_api_prefix() -> None:
    """A changed API_PREFIX must not open anything (the rules are prefix-free)."""
    with pytest.raises(DemoReadOnlyError):
        check_session_restrictions(
            "POST",
            "/v2/organizations/current/invites",
            api_prefix="/v2",
            is_demo=True,
            impersonating=False,
        )
    check_session_restrictions(
        "POST", "/v2/jobs/example", api_prefix="/v2", is_demo=True, impersonating=False
    )
    with pytest.raises(DemoReadOnlyError):  # the old prefix is not an API path any more
        check_session_restrictions(
            "POST", "/api/jobs/example", api_prefix="/v2", is_demo=True, impersonating=False
        )
