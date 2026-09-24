"""Seed the database with development data. Safe to run many times (idempotent).

Phase 1 has no tables yet, so this only checks the connection and the migration state.
Phase 4B adds the demo organization, demo user and realistic sample data.

Run: python -m app.scripts.seed
"""

from sqlalchemy import text

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.session import sync_session

logger = get_logger("seed")


def main() -> None:
    """Entry point."""
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    with sync_session() as session:
        revision = session.execute(text("SELECT version_num FROM alembic_version")).scalar()
        vector = session.execute(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        ).scalar()
    logger.info("seed_checked", alembic_revision=revision, pgvector_version=vector)
    logger.info("seed_done", note="No seed data yet. Demo data arrives in phase 4B.")


if __name__ == "__main__":
    main()
