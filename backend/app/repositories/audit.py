"""Audit log queries."""

import uuid
from datetime import datetime

from sqlalchemy import or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_key import ApiKey
from app.models.audit_log import AuditLog
from app.models.user import User

AuditRow = tuple[AuditLog, User | None, ApiKey | None]


class AuditRepository:
    """Append-only: insert, and read one workspace's events page by page."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, entry: AuditLog) -> None:
        """Insert one event (committed together with the change it describes)."""
        self._session.add(entry)
        await self._session.flush()

    async def list_for_org(
        self,
        organization_id: uuid.UUID,
        *,
        limit: int,
        before: tuple[datetime, uuid.UUID] | None = None,
        action_prefix: str | None = None,
    ) -> list[AuditRow]:
        """Newest first. `before` is the (created_at, id) of the last row of the previous page."""
        query = (
            select(AuditLog, User, ApiKey)
            .outerjoin(User, User.id == AuditLog.actor_user_id)
            .outerjoin(ApiKey, ApiKey.id == AuditLog.actor_api_key_id)
            .where(AuditLog.organization_id == organization_id)
        )
        if before is not None:
            query = query.where(tuple_(AuditLog.created_at, AuditLog.id) < before)
        if action_prefix:
            query = query.where(
                or_(
                    AuditLog.action == action_prefix,
                    AuditLog.action.startswith(action_prefix + ".", autoescape=True),
                )
            )
        rows = await self._session.execute(
            query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit)
        )
        return [(a, u, k) for a, u, k in rows.tuples()]
