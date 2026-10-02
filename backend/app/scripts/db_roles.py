"""Create or update the limited database user the running app connects as.

`./deploy.sh` runs this before every migration (it is safe to run again and again):

    MIGRATION_DATABASE_URL=<admin user>  DATABASE_URL=<runtime user, with its password>
    python -m app.scripts.db_roles

The runtime user's name and password come from DATABASE_URL (so there is only one place that
holds them). The admin connection comes from MIGRATION_DATABASE_URL. See app/db/roles.py.
"""

import sys

import psycopg
from sqlalchemy.engine import make_url

from app.core.config import get_settings
from app.db.roles import RoleSetupError, ensure_runtime_role


def main() -> int:
    """Entry point. Returns the exit code."""
    settings = get_settings()
    admin_url = (
        settings.migration_database_url.get_secret_value()
        if settings.migration_database_url
        else ""
    )
    if not admin_url:
        print("MIGRATION_DATABASE_URL is empty: there is no admin connection to use.")
        return 2
    admin = make_url(admin_url)
    runtime = make_url(settings.database_url)
    if (admin.host, admin.port, admin.database) != (runtime.host, runtime.port, runtime.database):
        print("DATABASE_URL and MIGRATION_DATABASE_URL must point to the same database.")
        return 2
    if not (admin.username and runtime.username and runtime.password and runtime.database):
        print("Both database URLs need a user, and DATABASE_URL needs a password and database.")
        return 2
    try:
        with psycopg.connect(
            host=admin.host,
            port=admin.port,
            dbname=admin.database,
            user=admin.username,
            password=admin.password,
            autocommit=True,
        ) as conn:
            ensure_runtime_role(
                conn,
                admin_role=admin.username,
                runtime_role=runtime.username,
                password=runtime.password,
                database=runtime.database,
            )
    except RoleSetupError as exc:
        print(f"ERROR: {exc}")
        return 1
    print(f"Database user '{runtime.username}' is ready (read/write rows only).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
