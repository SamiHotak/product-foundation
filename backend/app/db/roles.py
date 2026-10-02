"""The limited database role the running app uses (least privilege).

Two Postgres roles, two jobs:

- the ADMIN role (`app`, a superuser made by the Postgres image) creates tables. Only the
  deploy script uses it (migrations, backups). Its password never enters an app container.
- the RUNTIME role (`app_rt`) is what the API, the worker and beat connect as. It can read and
  write rows. It cannot create, change or drop tables, cannot create extensions, cannot run
  commands on the database server (`COPY ... PROGRAM`) and is not a superuser.

If someone ever breaks into the app, they get the data the app can reach (still serious) but
not the whole database server. `ensure_runtime_role` is safe to run on every deploy.
"""

import re
from typing import Final

import psycopg
from psycopg import sql

# Identifiers are quoted by psycopg, but we also keep them boring on purpose.
_NAME: Final = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


class RoleSetupError(Exception):
    """The role could not be set up safely (bad names, or admin and runtime are the same)."""


def _check_names(admin_role: str, runtime_role: str, database: str) -> None:
    for label, value in (
        ("admin role", admin_role),
        ("runtime role", runtime_role),
        ("database", database),
    ):
        if not _NAME.match(value):
            raise RoleSetupError(f"Strange {label} name: {value!r}")
    if admin_role == runtime_role:
        raise RoleSetupError(
            "DATABASE_URL and MIGRATION_DATABASE_URL use the same database user "
            f"({admin_role!r}). The app must run as a separate, limited user."
        )


def ensure_runtime_role(
    conn: psycopg.Connection,
    *,
    admin_role: str,
    runtime_role: str,
    password: str,
    database: str,
) -> None:
    """Create or update the runtime role and give it exactly row-level access.

    `conn` must be an autocommit connection to `database` made by the admin role. Running it
    again changes nothing except the password, and re-grants rights on new tables.
    """
    _check_names(admin_role, runtime_role, database)
    if not password:
        raise RoleSetupError("The runtime password is empty.")
    role = sql.Identifier(runtime_role)
    admin = sql.Identifier(admin_role)
    db = sql.Identifier(database)
    pw = sql.Literal(password)  # CREATE ROLE cannot take bind parameters; psycopg quotes safely
    flags = sql.SQL("LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT")

    # One transaction: the old app version keeps serving during a deploy, and must never see the
    # moment between "rights taken away" and "rights given back".
    with conn.transaction():
        exists = conn.execute(
            "SELECT 1 FROM pg_roles WHERE rolname = %s", (runtime_role,)
        ).fetchone()
        verb = "ALTER" if exists else "CREATE"
        conn.execute(sql.SQL("{} ROLE {} {} PASSWORD {}").format(sql.SQL(verb), role, flags, pw))

        statements: list[sql.SQL | sql.Composed] = [
            # Nobody gets in by default; only the roles we name.
            sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(db),
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(db, role),
            sql.SQL("REVOKE CREATE ON SCHEMA public FROM PUBLIC"),
            sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role),
            # Start from nothing, then give back exactly what the app needs. (Makes the result
            # the same no matter what an older version granted.)
            sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {}").format(role),
            sql.SQL("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {}").format(role),
            sql.SQL(
                "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {}"
            ).format(role),
            sql.SQL("GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO {}").format(
                role
            ),
            # Tables and sequences that FUTURE migrations create (they run as the admin role).
            sql.SQL(
                "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public "
                "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {}"
            ).format(admin, role),
            sql.SQL(
                "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public "
                "GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO {}"
            ).format(admin, role),
        ]
        for statement in statements:
            conn.execute(statement)

        # The migration history is not the app's to change.
        if conn.execute("SELECT to_regclass('public.alembic_version')").fetchone() != (None,):
            conn.execute(
                sql.SQL(
                    "REVOKE INSERT, UPDATE, DELETE ON TABLE public.alembic_version FROM {}"
                ).format(role)
            )
