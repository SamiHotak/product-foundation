"""Runtime switches (app/models/system_flag.py): read them anywhere, change them in /admin."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models.system_flag import FLAG_DEFAULTS, Flag, SystemFlag


def read_flag(session: Session, flag: Flag) -> bool:
    """A flag's value (sync: workers, the LLM gateway)."""
    value = session.scalar(select(SystemFlag.enabled).where(SystemFlag.key == flag.value))
    return FLAG_DEFAULTS[flag] if value is None else bool(value)


async def read_flag_async(session: AsyncSession, flag: Flag) -> bool:
    """A flag's value (async: API requests)."""
    value = await session.scalar(select(SystemFlag.enabled).where(SystemFlag.key == flag.value))
    return FLAG_DEFAULTS[flag] if value is None else bool(value)


async def write_flag(
    session: AsyncSession, flag: Flag, enabled: bool, *, user_id: uuid.UUID | None
) -> None:
    """Set a flag (the caller commits, together with the audit event)."""
    stmt = insert(SystemFlag).values(key=flag.value, enabled=enabled, updated_by_id=user_id)
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=[SystemFlag.key],
            set_={"enabled": enabled, "updated_by_id": user_id, "updated_at": func.now()},
        )
    )
