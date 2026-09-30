"""Files: upload in three steps, checks after upload, plan storage, roles, isolation,
virus scan, abandoned uploads and deleting a workspace's files."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from app.core.plans import DEFAULT_CATALOG
from app.db.session import sync_session
from app.models.audit_log import AuditLog
from app.models.file import FileStatus, StoredFile
from app.services.file_scan import (
    FileGone,
    ScanOutcome,
    remove_abandoned_uploads,
    remove_stale_staged,
    scan_file,
)
from app.services.jobs import JobService
from app.services.purge import purge_due
from app.services.virus_scan import ScannerUnavailableError
from tests.fakes import FakeScanner
from tests.helpers import World, build_world

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_db")]

PDF = b"%PDF-1.7\n" + b"x" * 200
CSV = b"name,price\nWedding film,2490\n"


@pytest.fixture
def world() -> World:
    return build_world()


async def _upload(
    world: World, c: AsyncClient, name: str, data: bytes, *, size: int | None = None
) -> Any:
    """Start, upload to the (fake) storage, complete. Returns the complete response."""
    res = await c.post(
        "/api/files/uploads", json={"filename": name, "size_bytes": size or len(data)}
    )
    assert res.status_code == 201, res.text
    started = res.json()
    key = started["upload"]["fields"]["key"]
    assert key.startswith("uploads/") and name not in key  # the name is never part of the path
    world.storage.upload(key, data)
    return await c.post(f"/api/files/{started['file']['id']}/complete")


async def test_upload_list_download_delete(world: World) -> None:
    async with world.client() as c:
        me = await world.signup_and_verify(c, "owner@example.com", "Olga")
        org = me["active_organization_id"]
        res = await c.post(
            "/api/files/uploads", json={"filename": "Price list.csv", "size_bytes": len(CSV)}
        )
        assert res.status_code == 201, res.text
        started = res.json()
        assert started["file"]["status"] == "uploading"
        assert started["upload"]["fields"]["Content-Type"] == "text/csv"
        key = started["upload"]["fields"]["key"]
        # The browser may only write to a staging key; the checked file lives elsewhere.
        assert key == f"uploads/{org}/{started['file']['id']}"
        final = f"orgs/{org}/files/{started['file']['id']}"
        # The storage gets the exact size as the limit (it refuses anything bigger).
        assert world.storage.posts[key] == {"max_bytes": len(CSV), "content_type": "text/csv"}
        # Not listed until it is complete.
        assert (await c.get("/api/files")).json()["items"] == []

        assert (await c.post(f"/api/files/{started['file']['id']}/complete")).status_code == 409
        world.storage.upload(key, CSV)
        done = await c.post(f"/api/files/{started['file']['id']}/complete")
        assert done.status_code == 200, done.text
        assert done.json()["file"]["status"] == "ready"
        assert done.json()["job_id"] is None
        assert key not in world.storage.objects and final in world.storage.objects
        again = await c.post(f"/api/files/{started['file']['id']}/complete")
        assert again.status_code == 409

        listed = (await c.get("/api/files")).json()
        assert listed["enabled"] is True
        assert "pdf" in listed["allowed_extensions"] and "html" not in listed["allowed_extensions"]
        [item] = listed["items"]
        assert item["filename"] == "Price list.csv"
        assert item["uploaded_by_name"] == "Olga" and item["can_delete"] is True

        link = (await c.post(f"/api/files/{item['id']}/download")).json()
        assert "download=Price list.csv" in link["url"]

        assert (await c.delete(f"/api/files/{item['id']}")).status_code == 204
        assert world.storage.objects == {}
        assert (await c.get("/api/files")).json()["items"] == []
        assert (await c.delete(f"/api/files/{item['id']}")).status_code == 404
        with sync_session() as s:
            actions = list(s.scalars(select(AuditLog.action).order_by(AuditLog.created_at)))
        assert "file.uploaded" in actions and "file.deleted" in actions


@pytest.mark.parametrize(
    ("name", "size", "message"),
    [
        ("page.html", 10, "can't be uploaded"),
        ("logo.svg", 10, "can't be uploaded"),
        ("setup.exe", 10, "can't be uploaded"),
        ("no-extension", 10, "can't be uploaded"),
        ("...", 10, "file name"),
        ("big.pdf", 26 * 1024 * 1024, "too big"),
    ],
)
async def test_names_types_and_sizes_are_checked_before_upload(
    world: World, name: str, size: int, message: str
) -> None:
    async with world.client() as c:
        await world.signup_and_verify(c, "owner@example.com")
        res = await c.post("/api/files/uploads", json={"filename": name, "size_bytes": size})
        assert res.status_code == 400, res.text
        assert res.json()["error"]["code"] == "invalid_file"
        assert message in res.json()["error"]["message"]
    assert world.storage.posts == {}


async def test_a_file_that_is_not_what_its_name_says_is_rejected_and_deleted(world: World) -> None:
    async with world.client() as c:
        await world.signup_and_verify(c, "owner@example.com")
        # A text file (e.g. a script) renamed to .png.
        res = await _upload(world, c, "photo.png", b"<script>alert(1)</script>")
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "file_rejected"
        assert "not a real PNG image" in res.json()["error"]["message"]
        assert world.storage.objects == {}
        # Binary junk named .txt.
        res = await _upload(world, c, "notes.txt", b"\x00\x01\x02binary")
        assert res.status_code == 400
        assert (await c.get("/api/files")).json()["items"] == []
        with sync_session() as s:
            statuses = set(s.scalars(select(StoredFile.status)))
        assert statuses == {FileStatus.REJECTED}
        # Real files of every kind pass.
        for name, data in [
            ("a.pdf", PDF),
            ("b.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 20),
            ("c.webp", b"RIFF\x00\x00\x00\x00WEBPVP8 "),
            ("d.docx", b"PK\x03\x04" + b"\x00" * 30),
            ("e.md", "# Überschrift\n\nText mit Umlauten: äöü ß\n".encode()),
            ("f.json", b'{"ok": true}'),
        ]:
            res = await _upload(world, c, name, data)
            assert res.status_code == 200, (name, res.text)
        assert len((await c.get("/api/files")).json()["items"]) == 6


async def test_the_real_size_counts_and_bigger_files_are_refused(world: World) -> None:
    async with world.client() as c:
        await world.signup_and_verify(c, "owner@example.com")
        res = await c.post("/api/files/uploads", json={"filename": "a.csv", "size_bytes": 10})
        started = res.json()
        key = started["upload"]["fields"]["key"]
        # The storage itself refuses a bigger file (content-length-range in the signed form).
        assert world.storage.upload(key, b"x" * 11) is False
        # A smaller file is fine; the real size is saved.
        world.storage.upload(key, b"a,b\n1,2\n")
        done = (await c.post(f"/api/files/{started['file']['id']}/complete")).json()
        assert done["file"]["size_bytes"] == 8
        # If a storage ever let a bigger file through, "complete" still refuses it.
        res = await c.post("/api/files/uploads", json={"filename": "b.csv", "size_bytes": 5})
        started = res.json()
        world.storage.put(started["upload"]["fields"]["key"], b"a,b\n1,2\n", "text/csv")
        res = await c.post(f"/api/files/{started['file']['id']}/complete")
        assert res.status_code == 400 and "bigger than announced" in res.text


async def test_an_upload_that_never_arrives_expires(world: World) -> None:
    async with world.client() as c:
        await world.signup_and_verify(c, "owner@example.com")
        res = await c.post("/api/files/uploads", json={"filename": "a.pdf", "size_bytes": 100})
        file_id = res.json()["file"]["id"]
        with sync_session() as s:
            s.execute(
                update(StoredFile).values(
                    upload_expires_at=datetime.now(UTC) - timedelta(minutes=1)
                )
            )
        res = await c.post(f"/api/files/{file_id}/complete")
        assert res.status_code == 400 and "took too long" in res.text


async def test_storage_limit_of_the_plan(world: World) -> None:
    world.catalog = DEFAULT_CATALOG  # free: 100 MB
    async with world.client() as c:
        me = await world.signup_and_verify(c, "owner@example.com")
        org = uuid.UUID(me["active_organization_id"])
        with sync_session() as s:
            s.add(
                StoredFile(
                    organization_id=org,
                    filename="old.pdf",
                    content_type="application/pdf",
                    size_bytes=99 * 1024 * 1024,
                    storage_key=f"orgs/{org}/files/{uuid.uuid4()}",
                    status=FileStatus.READY,
                    upload_expires_at=datetime.now(UTC),
                )
            )
        ok = await c.post(
            "/api/files/uploads", json={"filename": "a.pdf", "size_bytes": 512 * 1024}
        )
        assert ok.status_code == 201
        # The unfinished upload above counts too: 99.5 MB used, 1 MB more doesn't fit.
        res = await c.post(
            "/api/files/uploads", json={"filename": "b.pdf", "size_bytes": 1024 * 1024}
        )
        assert res.status_code == 402
        err = res.json()["error"]
        assert err["code"] == "limit_reached" and err["details"]["metric"] == "storage_mb"
        assert "100 MB" in err["message"]
        usage = {u["metric"]: u for u in (await c.get("/api/billing/current")).json()["usage"]}
        assert usage["storage_mb"]["used"] == 100 and usage["storage_mb"]["unit"] == "mb"


async def test_roles_api_keys_and_isolation(world: World) -> None:
    async with (
        world.client() as owner,
        world.client() as member,
        world.client() as other_member,
        world.client() as stranger,
        world.client() as script,
    ):
        await world.signup_and_verify(owner, "owner@example.com")
        await world.invite_and_join(owner, member, "m@example.com")
        await world.invite_and_join(owner, other_member, "m2@example.com", name="Other")
        await world.signup_and_verify(stranger, "stranger@example.com")
        mine = (await _upload(world, member, "mine.csv", CSV)).json()["file"]
        owners = (await _upload(world, owner, "owners.csv", CSV)).json()["file"]

        listed = {f["filename"]: f for f in (await other_member.get("/api/files")).json()["items"]}
        assert listed["mine.csv"]["can_delete"] is False
        # Members delete only their own files; owners and admins delete any.
        assert (await other_member.delete(f"/api/files/{mine['id']}")).status_code == 403
        assert (await member.delete(f"/api/files/{owners['id']}")).status_code == 403
        assert (await owner.delete(f"/api/files/{mine['id']}")).status_code == 204

        # Another workspace sees nothing.
        assert (await stranger.get("/api/files")).json()["items"] == []
        for method, path in [
            ("post", f"/api/files/{owners['id']}/download"),
            ("post", f"/api/files/{owners['id']}/complete"),
            ("delete", f"/api/files/{owners['id']}"),
        ]:
            assert (await getattr(stranger, method)(path)).status_code == 404

        # API keys: files:read lists and downloads; files:write uploads; nobody deletes.
        key = (
            await owner.post(
                "/api/organizations/current/api-keys",
                json={"name": "Sync", "scopes": ["files:read", "files:write"]},
            )
        ).json()["key"]
        bearer = {"Authorization": f"Bearer {key}"}
        items = (await script.get("/api/files", headers=bearer)).json()["items"]
        assert [f["can_delete"] for f in items] == [False]
        assert (
            await script.post(f"/api/files/{owners['id']}/download", headers=bearer)
        ).status_code == 200
        res = await script.post(
            "/api/files/uploads", json={"filename": "api.csv", "size_bytes": 10}, headers=bearer
        )
        assert res.status_code == 201
        assert (
            await script.delete(f"/api/files/{owners['id']}", headers=bearer)
        ).status_code == 403
        read_only = (
            await owner.post(
                "/api/organizations/current/api-keys", json={"name": "R", "scopes": ["jobs:read"]}
            )
        ).json()["key"]
        res = await script.get("/api/files", headers={"Authorization": f"Bearer {read_only}"})
        assert res.status_code == 403


async def test_files_switched_off_and_storage_down(world: World) -> None:
    from app.routers.deps import get_storage
    from app.services.storage import StorageError

    async with world.client() as c:
        await world.signup_and_verify(c, "owner@example.com")
        world.storage.fail_with = StorageError
        res = await c.post("/api/files/uploads", json={"filename": "a.pdf", "size_bytes": 10})
        assert res.status_code == 503 and "not reachable" in res.text
        world.app.dependency_overrides[get_storage] = lambda: None
        assert (await c.get("/api/files")).json()["enabled"] is False
        res = await c.post("/api/files/uploads", json={"filename": "a.pdf", "size_bytes": 10})
        assert res.status_code == 503 and "not set up" in res.text


async def test_virus_scan_after_upload(world: World) -> None:
    world.scanner = FakeScanner()
    async with world.client() as c:
        await world.signup_and_verify(c, "owner@example.com")
        clean = (await _upload(world, c, "clean.txt", b"hello world\n")).json()
        assert clean["file"]["status"] == "scanning" and clean["job_id"]
        # Still being scanned: no download yet, but it is listed.
        res = await c.post(f"/api/files/{clean['file']['id']}/download")
        assert res.status_code == 409
        infected = (await _upload(world, c, "eicar.txt", b"X5O!P%@AP EICAR test\n")).json()
        await world.run_jobs()
        jobs = {j["id"]: j for j in (await c.get("/api/jobs")).json()["items"]}
        assert jobs[clean["job_id"]]["status"] == "done"
        assert jobs[infected["job_id"]]["status"] == "failed"
        assert "virus" in jobs[infected["job_id"]]["error"]
        names = [f["filename"] for f in (await c.get("/api/files")).json()["items"]]
        assert names == ["clean.txt"]
        assert len(world.storage.objects) == 1
        assert (await c.post(f"/api/files/{clean['file']['id']}/download")).status_code == 200


async def test_scan_retries_then_gives_up(world: World) -> None:
    scanner = FakeScanner()
    scanner.unavailable = True
    world.scanner = scanner
    async with world.client() as c:
        await world.signup_and_verify(c, "owner@example.com")
        started = (await _upload(world, c, "a.txt", b"hello\n")).json()
    file_id = started["file"]["id"]
    with pytest.raises(ScannerUnavailableError):  # temporary: the job retries
        scan_file(file_id, world.storage, scanner)
    assert scan_file(file_id, world.storage, scanner, give_up=True) is ScanOutcome.GAVE_UP
    with sync_session() as s:
        row = s.get(StoredFile, uuid.UUID(file_id))
        assert row is not None and row.status is FileStatus.REJECTED
    assert world.storage.objects == {}
    with pytest.raises(FileGone):
        scan_file(file_id, world.storage, scanner)


async def test_abandoned_uploads_are_removed(world: World) -> None:
    async with world.client() as c:
        await world.signup_and_verify(c, "owner@example.com")
        fresh = (
            await c.post("/api/files/uploads", json={"filename": "a.pdf", "size_bytes": 9})
        ).json()
        old = (
            await c.post("/api/files/uploads", json={"filename": "b.pdf", "size_bytes": 9})
        ).json()
        world.storage.upload(
            old["upload"]["fields"]["key"], b"%PDF-1.4\n"
        )  # arrived, never completed
    with sync_session() as s:
        s.execute(
            update(StoredFile)
            .where(StoredFile.id == uuid.UUID(old["file"]["id"]))
            .values(upload_expires_at=datetime.now(UTC) - timedelta(hours=2))
        )
    assert remove_abandoned_uploads(sync_session, world.storage, datetime.now(UTC)) == 1
    assert world.storage.objects == {}
    with sync_session() as s:
        assert [str(i) for i in s.scalars(select(StoredFile.id))] == [fresh["file"]["id"]]


async def test_deleting_a_workspace_deletes_its_files(world: World) -> None:
    async with world.client() as c:
        me = await world.signup_and_verify(c, "owner@example.com")
        org = me["active_organization_id"]
        await _upload(world, c, "a.csv", CSV)
        res = await c.post(
            "/api/organizations/current/deletion", json={"confirm": me["organizations"][0]["name"]}
        )
        assert res.status_code in (200, 202), res.text
    deleted: list[str] = []

    def delete_files(organization_id: Any) -> None:
        deleted.append(str(organization_id))
        world.storage.delete_prefix(f"orgs/{organization_id}/")

    later = datetime.now(UTC) + timedelta(days=30)
    counts = purge_due(sync_session, later, None, delete_files)
    assert counts["workspaces"] == 1 and deleted == [org]
    assert world.storage.objects == {}


async def test_bytes_sent_again_after_the_check_are_never_served(world: World) -> None:
    """The signed form works for minutes: a second POST must not replace the checked file."""
    async with world.client() as c:
        me = await world.signup_and_verify(c, "owner@example.com")
        org = me["active_organization_id"]
        res = await c.post("/api/files/uploads", json={"filename": "a.pdf", "size_bytes": 9})
        started = res.json()
        key = started["upload"]["fields"]["key"]
        world.storage.upload(key, b"%PDF-1.4\n")
        done = await c.post(f"/api/files/{started['file']['id']}/complete")
        assert done.status_code == 200, done.text
        # Same form again, other bytes: they land in staging only.
        assert world.storage.upload(key, b"MZ-evil!!") is True
        final = f"orgs/{org}/files/{started['file']['id']}"
        assert world.storage.objects[final][0] == b"%PDF-1.4\n"
        assert (await c.post(f"/api/files/{started['file']['id']}/complete")).status_code == 409
    # The nightly clean-up deletes old staged bytes.
    assert remove_stale_staged(world.storage, datetime.now(UTC)) == 0  # too young
    assert remove_stale_staged(world.storage, datetime.now(UTC) + timedelta(days=2)) == 1
    assert list(world.storage.objects) == [final]


async def test_an_upload_cannot_be_deleted_while_its_form_works(world: World) -> None:
    async with world.client() as c:
        await world.signup_and_verify(c, "owner@example.com")
        res = await c.post("/api/files/uploads", json={"filename": "a.pdf", "size_bytes": 9})
        file_id = res.json()["file"]["id"]
        res = await c.delete(f"/api/files/{file_id}")
        assert res.status_code == 409 and "still uploading" in res.text
        with sync_session() as s:
            s.execute(
                update(StoredFile)
                .where(StoredFile.id == uuid.UUID(file_id))
                .values(upload_expires_at=datetime.now(UTC) - timedelta(minutes=1))
            )
        assert (await c.delete(f"/api/files/{file_id}")).status_code == 204


async def test_a_scan_that_cannot_start_rejects_the_file(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.scanner = FakeScanner()

    async def broken(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("broker down")

    monkeypatch.setattr(JobService, "enqueue", broken)
    async with world.client() as c:
        await world.signup_and_verify(c, "owner@example.com")
        res = await _upload(world, c, "a.txt", b"hello\n")
        assert res.status_code == 503, res.text
        with sync_session() as s:
            [row] = list(s.scalars(select(StoredFile)))
            assert row.status is FileStatus.REJECTED
    assert world.storage.objects == {}
