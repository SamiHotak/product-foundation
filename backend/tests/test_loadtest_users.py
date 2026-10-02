"""The load test helper script: its users and sessions really work, and cleanup is exact."""

import json
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.core.config import Environment, get_settings
from app.db.session import sync_session
from app.models.organization import Organization
from app.models.user import User
from app.scripts import loadtest_users
from tests.helpers import World, build_world

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_db")]


@pytest.fixture
def world() -> World:
    return build_world()


async def test_sessions_and_passwords_work_through_the_real_api(
    world: World, tmp_path: Path
) -> None:
    out = tmp_path / "users.json"
    assert loadtest_users.main(["--users", "3", "--out", str(out)]) == 0
    assert oct(out.stat().st_mode & 0o777) == "0o600"  # holds live session cookies
    data = json.loads(out.read_text())
    assert data["cookie_name"] == get_settings().session_cookie_name
    assert len(data["users"]) == 3

    first = data["users"][0]
    async with world.client() as browser:
        browser.cookies.set(data["cookie_name"], first["token"])
        me = await browser.get("/api/auth/me")
        assert me.status_code == 200
        assert me.json()["user"]["email"] == first["email"]
        assert (await browser.get("/api/organizations/current/members")).status_code == 200

    async with world.client() as fresh:  # the password is real too (the login scenario)
        res = await fresh.post(
            "/api/auth/login", json={"email": first["email"], "password": first["password"]}
        )
        assert res.status_code == 200, res.text


async def test_running_twice_does_not_duplicate_users(tmp_path: Path) -> None:
    loadtest_users.main(["--users", "2", "--out", str(tmp_path / "a.json")])
    loadtest_users.main(["--users", "2", "--out", str(tmp_path / "b.json")])
    with sync_session() as session:
        assert session.scalar(select(func.count()).select_from(User)) == 2
        assert session.scalar(select(func.count()).select_from(Organization)) == 2


async def test_cleanup_deletes_only_the_test_data(world: World, tmp_path: Path) -> None:
    async with world.client() as real:
        await world.signup_and_verify(real, "real@example.com", "Real Person")
    loadtest_users.main(["--users", "3", "--out", str(tmp_path / "u.json")])
    assert loadtest_users.main(["--cleanup"]) == 0
    with sync_session() as session:
        emails = list(session.scalars(select(User.email)))
        assert emails == ["real@example.com"]
        names = list(session.scalars(select(Organization.name)))
        assert len(names) == 1
        assert not names[0].startswith(loadtest_users.WORKSPACE_PREFIX)


async def test_cleanup_keeps_a_real_workspace_with_a_look_alike_name(
    world: World, tmp_path: Path
) -> None:
    async with world.client() as real:
        await world.signup_and_verify(real, "real@example.com", "Real Person")
        renamed = await real.patch(
            "/api/organizations/current", json={"name": "Loadtest workspace Acme"}
        )
        assert renamed.status_code == 200, renamed.text
    loadtest_users.main(["--users", "2", "--out", str(tmp_path / "u.json")])
    assert loadtest_users.main(["--cleanup"]) == 0
    with sync_session() as session:
        assert list(session.scalars(select(Organization.name))) == ["Loadtest workspace Acme"]
        assert list(session.scalars(select(User.email))) == ["real@example.com"]


async def test_every_run_uses_a_new_password_and_the_old_one_stops_working(
    world: World, tmp_path: Path
) -> None:
    first_file, second_file = tmp_path / "a.json", tmp_path / "b.json"
    loadtest_users.main(["--users", "1", "--out", str(first_file)])
    loadtest_users.main(["--users", "1", "--out", str(second_file)])
    old = json.loads(first_file.read_text())["users"][0]
    new = json.loads(second_file.read_text())["users"][0]
    assert old["password"] != new["password"]
    async with world.client() as browser:
        bad = await browser.post(
            "/api/auth/login", json={"email": old["email"], "password": old["password"]}
        )
        assert bad.status_code in (400, 401)
        good = await browser.post(
            "/api/auth/login", json={"email": new["email"], "password": new["password"]}
        )
        assert good.status_code == 200, good.text


def test_the_session_file_is_private_even_if_an_old_one_was_open(tmp_path: Path) -> None:
    out = tmp_path / "u.json"
    out.write_text("old")
    out.chmod(0o644)
    assert loadtest_users.main(["--users", "1", "--out", str(out)]) == 0
    assert oct(out.stat().st_mode & 0o777) == "0o600"


def test_it_does_not_write_through_a_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    target.write_text("keep")
    link = tmp_path / "u.json"
    link.symlink_to(target)
    with pytest.raises(OSError):
        loadtest_users.main(["--users", "1", "--out", str(link)])
    assert target.read_text() == "keep"


def test_refuses_production_without_the_flag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(get_settings(), "environment", Environment.PRODUCTION)
    out = tmp_path / "u.json"
    assert loadtest_users.main(["--out", str(out)]) == 1
    assert "PRODUCTION" in capsys.readouterr().out
    assert not out.exists()
    assert loadtest_users.main(["--cleanup"]) == 1  # not even cleanup, by accident


def test_user_count_is_limited(tmp_path: Path) -> None:
    assert loadtest_users.main(["--users", "0", "--out", str(tmp_path / "u.json")]) == 2
    assert loadtest_users.main(["--users", "100000", "--out", str(tmp_path / "u.json")]) == 2
