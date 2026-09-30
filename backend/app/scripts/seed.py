"""Seed the database with development data. Safe to run many times (idempotent).

Creates the "Try the demo" workspace (demo user, a small team, jobs, files, AI usage).
With --reset it deletes the demo data first (like the nightly reset).

Run: python -m app.scripts.seed [--reset]      (or: make seed / make seed ARGS=--reset)
"""

import argparse

from sqlalchemy import text

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.session import sync_session
from app.services.demo import reset_demo_data, seed_demo
from app.services.storage import storage_for

logger = get_logger("seed")


def main(argv: list[str] | None = None) -> None:
    """Entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="delete the demo data first")
    args = parser.parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    with sync_session() as session:
        revision = session.execute(text("SELECT version_num FROM alembic_version")).scalar()
    logger.info("seed_checked", alembic_revision=revision)
    storage = storage_for(settings)
    if args.reset:
        counts = reset_demo_data(settings, storage)
        logger.info("demo_reset", **counts)
    else:
        seed_demo(settings, storage)
    note = "" if settings.demo_enabled else " (DEMO_ENABLED is off: the button is hidden)"
    print(f"Demo data ready. Sign in with 'Try the demo' on /login{note}.")
    if storage is None:
        print("File storage is not configured, so the demo has no files.")


if __name__ == "__main__":
    main()
