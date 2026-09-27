"""Small "has this happened yet?" queries for the onboarding checklist (one workspace)."""

import uuid

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_key import ApiKey
from app.models.invite import Invite
from app.models.job import Job
from app.models.organization import Membership
from app.workers.registry import PRIVATE_JOB_KINDS


class OnboardingRepository:
    """Every query is scoped to one organization."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def member_count(self, organization_id: uuid.UUID) -> int:
        """People in the workspace."""
        count = await self._session.scalar(
            select(func.count())
            .select_from(Membership)
            .where(Membership.organization_id == organization_id)
        )
        return int(count or 0)

    async def has_invite(self, organization_id: uuid.UUID) -> bool:
        """Anyone was ever invited (open, accepted or cancelled)."""
        return bool(
            await self._session.scalar(
                select(exists().where(Invite.organization_id == organization_id))
            )
        )

    async def has_api_key(self, organization_id: uuid.UUID) -> bool:
        """An API key was ever created (revoked ones count: the step was learned)."""
        return bool(
            await self._session.scalar(
                select(exists().where(ApiKey.organization_id == organization_id))
            )
        )

    async def has_job(self, organization_id: uuid.UUID) -> bool:
        """A (workspace-visible) background job was started. Private data exports don't count."""
        return bool(
            await self._session.scalar(
                select(
                    exists().where(
                        Job.organization_id == organization_id,
                        Job.kind.not_in(PRIVATE_JOB_KINDS),
                    )
                )
            )
        )
