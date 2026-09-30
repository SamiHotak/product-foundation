"""AI features for the API: is AI available, and start AI background jobs.

AI calls run in background jobs (they take seconds). The job calls the LLM gateway
(app/llm/gateway.py), which counts the plan's "AI requests". Here we only check early,
so people see "limit reached" or "AI is paused" at once instead of in a failed job.
"""

import asyncio
from typing import Literal, cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import Permission
from app.core.plans import PlanCatalog
from app.core.restrictions import DemoReadOnlyError
from app.llm.gateway import AiUnavailableError, LlmGateway
from app.llm.samples import SUMMARY_SAMPLES, is_summary_sample
from app.models.job import Job
from app.schemas.ai import AiStatus
from app.services.jobs import JobService
from app.services.organizations import OrgContext
from app.services.usage import UsageService

Provider = Literal["openai", "fake", "none"]


class AiService:
    """AI status and AI jobs for one request."""

    def __init__(
        self, db: AsyncSession, gateway: LlmGateway, jobs: JobService, catalog: PlanCatalog
    ) -> None:
        self._gateway = gateway
        self._jobs = jobs
        self._usage = UsageService(db, catalog)

    async def status(self, ctx: OrgContext) -> AiStatus:
        """What the dashboard shows."""
        reason = await asyncio.to_thread(self._gateway.availability)
        return AiStatus(
            available=reason is None,
            reason=reason,
            provider=cast(Provider, self._gateway.provider_name),
            can_use=ctx.can(Permission.AI_USE),
            sample_text=SUMMARY_SAMPLES[0],
            samples_only=ctx.user.is_demo,
        )

    async def start_summary(self, ctx: OrgContext, text: str) -> Job:
        """Queue a summary job. The worker calls the model."""
        ctx.require(Permission.AI_USE)
        if ctx.user.is_demo and not is_summary_sample(text):
            # Shared account: other visitors would see this text, and it would cost money.
            raise DemoReadOnlyError(
                "In the shared demo you can summarize the sample text. Create your own free "
                "account to summarize your own texts."
            )
        reason = await asyncio.to_thread(self._gateway.availability)
        if reason:
            raise AiUnavailableError(reason)
        await self._usage.check_available(ctx.organization.id, "ai_requests_per_month")
        return await self._jobs.enqueue(
            "ai_summary",
            {"text": text},
            organization_id=ctx.organization.id,
            created_by_id=ctx.user.id,
        )
