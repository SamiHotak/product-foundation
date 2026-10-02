"""The limited database user (least privilege): real Postgres.

Proves what docs/SECURITY.md promises: the user the running app connects as can read and write
rows (also in tables that a LATER migration creates), and can do nothing else: no DDL, no
extensions, no commands on the database server, no new roles.
"""

import os
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from psycopg import errors
from sqlalchemy import create_engine
from sqlalchemy.engine import URL, make_url

from app.core.config import get_settings
from app.db.roles import RoleSetupError, ensure_runtime_role
from app.models import Base
from app.scripts import db_roles as db_roles_script

pytestmark = pytest.mark.integration

SCRATCH_DB = "app_roles_scratch"
ROLE = "app_rt_scratch"


def _admin_url(database: str) -> URL:
    base = make_url(os.environ["DATABASE_URL"])
    return base.set(drivername="postgresql", database=database)


def _connect(url: URL, **kwargs: Any) -> psycopg.Connection:
    # Fields, not a URL string: a URL cannot carry every character a password may have.
    return psycopg.connect(
        host=url.host,
        port=url.port,
        dbname=url.database,
        user=url.username,
        password=url.password,
        **kwargs,
    )


@pytest.fixture
def scratch() -> Iterator[URL]:
    """A throw-away database with the real tables, and no runtime role yet."""
    from tests.conftest import RUN_INTEGRATION

    if not RUN_INTEGRATION:
        pytest.skip("set RUN_INTEGRATION=1")
    with _connect(_admin_url("postgres"), autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{SCRATCH_DB}" WITH (FORCE)')
        conn.execute(f'DROP ROLE IF EXISTS "{ROLE}"')
        conn.execute(f'CREATE DATABASE "{SCRATCH_DB}"')
    url = _admin_url(SCRATCH_DB)
    with _connect(url, autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.execute("CREATE EXTENSION IF NOT EXISTS citext")
    yield url
    with _connect(_admin_url("postgres"), autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{SCRATCH_DB}" WITH (FORCE)')
        conn.execute(f'DROP ROLE IF EXISTS "{ROLE}"')


def _setup(url: URL, password: str = "first-password") -> None:
    with _connect(url, autocommit=True) as conn:
        ensure_runtime_role(
            conn,
            admin_role=str(url.username),
            runtime_role=ROLE,
            password=password,
            database=SCRATCH_DB,
        )


def _runtime(url: URL, password: str = "first-password") -> psycopg.Connection:
    return _connect(url.set(username=ROLE, password=password), autocommit=True)


def _create_tables(url: URL) -> None:
    engine = create_engine(url.set(drivername="postgresql+psycopg"))
    Base.metadata.create_all(engine)
    engine.dispose()


def test_role_is_not_powerful(scratch: URL) -> None:
    _setup(scratch)
    with _connect(scratch) as conn:
        row = conn.execute(
            "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls "
            "FROM pg_roles WHERE rolname = %s",
            (ROLE,),
        ).fetchone()
    assert row == (False, False, False, False, False)


def test_existing_and_future_tables_get_row_access_only(scratch: URL) -> None:
    _create_tables(scratch)  # tables that already exist when the role is set up ...
    _setup(scratch)
    with _connect(scratch, autocommit=True) as admin:  # ... and one a later migration adds
        admin.execute("CREATE TABLE probe_later (id serial PRIMARY KEY, note text)")
    tables = [t.name for t in Base.metadata.sorted_tables] + ["probe_later"]
    with _connect(scratch) as admin:
        for table in tables:
            for right, expected in (
                ("SELECT", True),
                ("INSERT", True),
                ("UPDATE", True),
                ("DELETE", True),
                ("TRUNCATE", False),
                ("REFERENCES", False),
                ("TRIGGER", False),
            ):
                if table == "alembic_version":
                    continue
                allowed = admin.execute(
                    "SELECT has_table_privilege(%s, %s, %s)", (ROLE, f"public.{table}", right)
                ).fetchone()
                assert allowed == (expected,), f"{table}: {right}"
    with _runtime(scratch) as conn:  # the sequence of the new table works too
        conn.execute("INSERT INTO probe_later (note) VALUES ('a'), ('b')")
        assert conn.execute("SELECT count(*) FROM probe_later").fetchone() == (2,)
        conn.execute("UPDATE probe_later SET note = 'c' WHERE note = 'a'")
        conn.execute("DELETE FROM probe_later WHERE note = 'b'")
        assert conn.execute("SELECT count(*) FROM probe_later").fetchone() == (1,)


@pytest.mark.parametrize(
    "statement",
    [
        "TRUNCATE probe",
        "DROP TABLE probe",
        "ALTER TABLE probe ADD COLUMN extra int",
        "CREATE TABLE sneaky (id int)",
        "CREATE INDEX sneaky_idx ON probe (note)",
        "CREATE EXTENSION IF NOT EXISTS hstore",
        "COPY (SELECT 1) TO PROGRAM 'id'",
        "COPY probe FROM '/etc/passwd'",
        "CREATE ROLE sneaky LOGIN",
        "ALTER ROLE app_rt_scratch SUPERUSER",
        "SELECT rolpassword FROM pg_authid",
        "CREATE SCHEMA sneaky",
    ],
)
def test_role_cannot_change_the_database_itself(scratch: URL, statement: str) -> None:
    with _connect(scratch, autocommit=True) as admin:
        admin.execute("CREATE TABLE probe (id serial PRIMARY KEY, note text)")
    _setup(scratch)
    with _runtime(scratch) as conn, pytest.raises(errors.InsufficientPrivilege):
        conn.execute(statement.encode())


def test_migration_history_is_read_only(scratch: URL) -> None:
    with _connect(scratch, autocommit=True) as admin:
        admin.execute("CREATE TABLE alembic_version (version_num varchar(32) NOT NULL)")
        admin.execute("INSERT INTO alembic_version VALUES ('abc')")
    _setup(scratch)
    with _runtime(scratch) as conn:
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone() == ("abc",)
        with pytest.raises(errors.InsufficientPrivilege):
            conn.execute("UPDATE alembic_version SET version_num = 'x'")
        with pytest.raises(errors.InsufficientPrivilege):
            conn.execute("DELETE FROM alembic_version")


def test_other_databases_are_closed_to_it_by_default(scratch: URL) -> None:
    """Only the app database lists the role as allowed to connect."""
    _setup(scratch)
    with _connect(scratch) as admin:
        allowed = admin.execute(
            "SELECT has_database_privilege(%s, %s, 'CONNECT')", (ROLE, SCRATCH_DB)
        ).fetchone()
        temp = admin.execute(
            "SELECT has_database_privilege(%s, %s, 'TEMPORARY')", (ROLE, SCRATCH_DB)
        ).fetchone()
        create = admin.execute(
            "SELECT has_database_privilege(%s, %s, 'CREATE')", (ROLE, SCRATCH_DB)
        ).fetchone()
    assert (allowed, temp, create) == ((True,), (False,), (False,))


def test_running_twice_is_safe_and_changes_the_password(scratch: URL) -> None:
    _setup(scratch, "first-password")
    _setup(scratch, "second-password")
    with pytest.raises(psycopg.OperationalError):
        _runtime(scratch, "first-password")
    with _runtime(scratch, "second-password") as conn:
        assert conn.execute("SELECT 1").fetchone() == (1,)


def test_a_strange_password_is_quoted_safely(scratch: URL) -> None:
    nasty = 'it\'s a "test"; DROP TABLE x; --\\'
    _setup(scratch, nasty)
    with _runtime(scratch, nasty) as conn:
        assert conn.execute("SELECT 1").fetchone() == (1,)


@pytest.mark.parametrize(
    ("admin_role", "runtime_role", "database"),
    [
        ("app", "app", "app"),  # the app must not run as the admin
        ("app", "App; DROP", "app"),
        ("app", "app_rt", 'a"b'),
        ("", "app_rt", "app"),
    ],
)
def test_bad_names_are_refused(
    scratch: URL, admin_role: str, runtime_role: str, database: str
) -> None:
    with _connect(scratch, autocommit=True) as conn, pytest.raises(RoleSetupError):
        ensure_runtime_role(
            conn,
            admin_role=admin_role,
            runtime_role=runtime_role,
            password="x",
            database=database,
        )


def test_an_empty_password_is_refused(scratch: URL) -> None:
    with _connect(scratch, autocommit=True) as conn, pytest.raises(RoleSetupError):
        ensure_runtime_role(
            conn, admin_role="app", runtime_role=ROLE, password="", database=SCRATCH_DB
        )


# --- the command used by ./deploy.sh ------------------------------------------------------


@pytest.fixture
def script_env(scratch: URL, monkeypatch: pytest.MonkeyPatch) -> Iterator[URL]:
    sqla = scratch.set(drivername="postgresql+psycopg")
    monkeypatch.setenv("MIGRATION_DATABASE_URL", sqla.render_as_string(hide_password=False))
    monkeypatch.setenv(
        "DATABASE_URL",
        sqla.set(username=ROLE, password="script-password").render_as_string(hide_password=False),
    )
    get_settings.cache_clear()
    yield scratch
    get_settings.cache_clear()


def test_script_sets_up_the_role(script_env: URL, capsys: pytest.CaptureFixture[str]) -> None:
    assert db_roles_script.main() == 0
    assert ROLE in capsys.readouterr().out
    with _runtime(script_env, "script-password") as conn:
        assert conn.execute("SELECT 1").fetchone() == (1,)


def test_script_needs_the_admin_url(
    script_env: URL, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("MIGRATION_DATABASE_URL", "")
    get_settings.cache_clear()
    assert db_roles_script.main() == 2
    assert "MIGRATION_DATABASE_URL is empty" in capsys.readouterr().out


def test_script_refuses_two_different_databases(
    script_env: URL, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    other = script_env.set(drivername="postgresql+psycopg", database="somewhere_else")
    monkeypatch.setenv("DATABASE_URL", other.render_as_string(hide_password=False))
    get_settings.cache_clear()
    assert db_roles_script.main() == 2
    assert "same database" in capsys.readouterr().out


def test_script_refuses_to_run_the_app_as_the_admin(
    script_env: URL, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    same = script_env.set(drivername="postgresql+psycopg")
    monkeypatch.setenv("DATABASE_URL", same.render_as_string(hide_password=False))
    get_settings.cache_clear()
    assert db_roles_script.main() == 1
    assert "separate, limited user" in capsys.readouterr().out
