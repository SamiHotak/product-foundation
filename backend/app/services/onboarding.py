"""The "Get started" checklist: which first steps are done in the active workspace.

The backend only answers "done or not" per step key. Titles, texts and links live in the
frontend (frontend/config/product.ts), so a product changes the wording in one place.

A product adds a step in three places:
1. `OnboardingStepKey` in app/schemas/account.py,
2. a check in `OnboardingService._checks` below,
3. the step's text and link in frontend/config/product.ts (`onboarding`).
"""

from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import Permission
from app.repositories.onboarding import OnboardingRepository
from app.schemas.account import OnboardingStatus, OnboardingStep, OnboardingStepKey
from app.services.organizations import OrgContext
from app.services.sessions import utcnow

Check = Callable[[OrgContext], Awaitable[bool]]


class OnboardingService:
    """Checklist status and hiding it (per person, per workspace)."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._repo = OnboardingRepository(db)

    def _checks(self, ctx: OrgContext) -> list[tuple[OnboardingStepKey, Check]]:
        """Steps in display order. Steps you can't do (no permission) are left out."""
        org_id = ctx.organization.id

        async def verified(c: OrgContext) -> bool:
            return c.user.is_verified

        async def teammate(c: OrgContext) -> bool:
            return await self._repo.member_count(org_id) > 1 or await self._repo.has_invite(org_id)

        async def api_key(c: OrgContext) -> bool:
            return await self._repo.has_api_key(org_id)

        async def job(c: OrgContext) -> bool:
            return await self._repo.has_job(org_id)

        steps: list[tuple[OnboardingStepKey, Check]] = [("verify_email", verified)]
        if ctx.can(Permission.MEMBERS_INVITE):
            steps.append(("invite_teammate", teammate))
        if ctx.can(Permission.API_KEYS_MANAGE):
            steps.append(("create_api_key", api_key))
        if ctx.can(Permission.JOBS_WRITE):
            steps.append(("run_job", job))
        return steps

    async def status(self, ctx: OrgContext) -> OnboardingStatus:
        """Every step with done / not done."""
        steps = [OnboardingStep(key=key, done=await check(ctx)) for key, check in self._checks(ctx)]
        return OnboardingStatus(
            steps=steps, dismissed=ctx.membership.onboarding_dismissed_at is not None
        )

    async def dismiss(self, ctx: OrgContext) -> OnboardingStatus:
        """Hide the checklist for this person in this workspace."""
        if ctx.membership.onboarding_dismissed_at is None:
            ctx.membership.onboarding_dismissed_at = utcnow()
            await self._db.commit()
        return await self.status(ctx)

    async def restore(self, ctx: OrgContext) -> OnboardingStatus:
        """Show the checklist again (the "Undo" after hiding it)."""
        if ctx.membership.onboarding_dismissed_at is not None:
            ctx.membership.onboarding_dismissed_at = None
            await self._db.commit()
        return await self.status(ctx)
