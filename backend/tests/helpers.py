"""Helpers for integration tests: a real app on the test database with fake outside services."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from typing import Annotated, Any
from unittest.mock import patch

from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.plans import DEFAULT_CATALOG, PlanCatalog, PlanLimits
from app.core.rate_limit import MemoryRateLimiter, get_rate_limiter
from app.db.session import get_db
from app.llm.gateway import LlmGateway
from app.main import create_app
from app.models.job import Job
from app.repositories.jobs import JobRepository
from app.routers.deps import (
    get_email_sender,
    get_google_client,
    get_job_dispatcher,
    get_llm_gateway,
    get_payment_gateway,
    get_plan_catalog,
    get_storage,
    get_virus_scanner,
)
from app.routers.jobs import get_job_service
from app.services.jobs import JobService
from app.services.usage import UsageService
from app.workers.registry import JOB_TASKS
from tests.fakes import (
    FakeEmailSender,
    FakeGateway,
    FakeGoogleClient,
    FakeScanner,
    FakeStorage,
    ListTracer,
    ScriptedProvider,
)

PASSWORD = "correct horse battery"


def roomy_catalog() -> PlanCatalog:
    """The real plans, but the free plan has no limits.

    Most tests are about their own feature (invites, keys, jobs), not about plan limits.
    Limits are tested with the real plans in test_billing_*.py and test_usage_limits.py.
    """
    plans = tuple(
        replace(
            p,
            limits=PlanLimits(
                members=None,
                jobs_per_month=None,
                api_keys=None,
                storage_mb=None,
                ai_requests_per_month=None,
            ),
        )
        if p.id == DEFAULT_CATALOG.free.id
        else p
        for p in DEFAULT_CATALOG.plans
    )
    return PlanCatalog(plans)


@dataclass
class World:
    """The app plus every fake, so tests can look inside."""

    app: FastAPI
    email: FakeEmailSender = field(default_factory=FakeEmailSender)
    limiter: MemoryRateLimiter = field(default_factory=MemoryRateLimiter)
    google: FakeGoogleClient = field(default_factory=FakeGoogleClient)
    stripe: FakeGateway = field(default_factory=FakeGateway)
    catalog: PlanCatalog = field(default_factory=roomy_catalog)
    dispatched: list[Job] = field(default_factory=list)
    storage: FakeStorage = field(default_factory=FakeStorage)
    # None = no virus scanner configured. Set `world.scanner = FakeScanner()` to scan.
    scanner: FakeScanner | None = None
    provider: ScriptedProvider = field(default_factory=ScriptedProvider)
    traces: ListTracer = field(default_factory=ListTracer)

    def gateway(self) -> LlmGateway:
        """The LLM gateway the app and the worker use in this test."""
        from app.db.session import sync_session

        return LlmGateway(
            get_settings_for(self.app),
            self.provider,
            sync_session,
            catalog=self.catalog,
            tracer=self.traces,
            sleep=lambda _seconds: None,
        )

    @asynccontextmanager
    async def client(self, **headers: str) -> AsyncIterator[AsyncClient]:
        """A browser-like client with its own cookie jar."""
        transport = ASGITransport(app=self.app, raise_app_exceptions=False)
        async with AsyncClient(
            transport=transport, base_url="http://test", headers=headers, follow_redirects=False
        ) as c:
            yield c

    async def signup_and_verify(
        self, c: AsyncClient, email: str, name: str = "Ezat Test"
    ) -> dict[str, Any]:
        """Sign up, open the email link, return /me. The client is signed in afterwards."""
        res = await c.post(
            "/api/auth/signup", json={"name": name, "email": email, "password": PASSWORD}
        )
        assert res.status_code == 202, res.text
        res = await c.post("/api/auth/verify-email", json={"token": self.email.link_token(email)})
        assert res.status_code == 200, res.text
        body: dict[str, Any] = res.json()
        return body

    def settings(self, **changes: Any) -> Settings:
        """Use changed settings for the rest of the test (e.g. lower limits)."""
        changed = get_settings().model_copy(update=changes)
        self.app.dependency_overrides[get_settings] = lambda: changed
        return changed

    async def run_jobs(self) -> None:
        """Run every queued job now, in-process, with the real worker code and database."""
        import app.workers.tasks  # noqa: F401 - registers the tasks
        from app.workers.celery_app import celery_app

        pending, self.dispatched[:] = list(self.dispatched), []
        gateway = self.gateway()
        with (
            patch.object(LlmGateway, "from_settings", lambda _settings: gateway),
            patch("app.services.storage.storage_for", lambda _settings: self.storage),
            patch("app.services.virus_scan.scanner_for", lambda _settings: self.scanner),
        ):
            for job in pending:
                task = celery_app.tasks[JOB_TASKS[job.kind]]
                kwargs: dict[str, Any] = {"job_id": str(job.id), **job.params}
                if job.kind == "example":
                    kwargs["delay_seconds"] = 0
                await asyncio.to_thread(task.apply, kwargs=kwargs, task_id=str(job.id))

    async def invite_and_join(
        self,
        inviter: AsyncClient,
        invitee: AsyncClient,
        email: str,
        role: str = "member",
        name: str = "New Person",
    ) -> dict[str, Any]:
        """Invite `email` and let `invitee` (signed out) create an account from the link."""
        res = await inviter.post(
            "/api/organizations/current/invites", json={"email": email, "role": role}
        )
        assert res.status_code == 201, res.text
        res = await invitee.post(
            "/api/invites/signup",
            json={"token": self.email.link_token(email), "name": name, "password": PASSWORD},
        )
        assert res.status_code == 200, res.text
        body: dict[str, Any] = res.json()
        return body


def build_world(catalog: PlanCatalog | None = None, **settings_changes: Any) -> World:
    """Real app + real test database; email, rate limits, Google, Stripe and the job queue
    are fakes. `catalog`: the plans (default: real plans with an unlimited free plan).
    `settings_changes`: settings the app is BUILT with (e.g. billing_dev_tools=True)."""
    settings = get_settings()
    if settings_changes:
        settings = settings.model_copy(update=settings_changes)
    world = World(app=create_app(settings))
    if settings_changes:
        world.app.dependency_overrides[get_settings] = lambda: settings
    if catalog is not None:
        world.catalog = catalog
    app = world.app

    async def dispatch(job: Job) -> None:
        world.dispatched.append(job)

    def job_service(session: Annotated[AsyncSession, Depends(get_db)]) -> JobService:
        return JobService(JobRepository(session), dispatch, UsageService(session, world.catalog))

    app.dependency_overrides[get_email_sender] = lambda: world.email
    app.dependency_overrides[get_rate_limiter] = lambda: world.limiter
    app.dependency_overrides[get_google_client] = lambda: world.google
    app.dependency_overrides[get_job_service] = job_service
    app.dependency_overrides[get_plan_catalog] = lambda: world.catalog
    app.dependency_overrides[get_payment_gateway] = lambda: world.stripe
    app.dependency_overrides[get_storage] = lambda: world.storage
    app.dependency_overrides[get_virus_scanner] = lambda: world.scanner
    app.dependency_overrides[get_llm_gateway] = world.gateway
    app.dependency_overrides[get_job_dispatcher] = lambda: dispatch
    return world


def get_settings_for(app: FastAPI) -> Settings:
    """The settings this app runs with (changed ones, if the test changed them)."""
    override = app.dependency_overrides.get(get_settings)
    return override() if override else get_settings()


def set_plan(
    organization_id: str,
    plan_id: str | None,
    *,
    status: str = "active",
    customer_id: str | None = None,
    subscription_id: str | None = None,
) -> None:
    """Put a workspace on a plan directly in the database (like a finished checkout)."""
    import uuid as _uuid

    from sqlalchemy.dialects.postgresql import insert

    from app.db.session import sync_session
    from app.models.billing import Subscription

    values = {
        "plan_id": plan_id,
        "status": status,
        "interval": "month",
        "stripe_customer_id": customer_id or f"cus_{_uuid.uuid4().hex[:12]}",
        "stripe_subscription_id": subscription_id or f"sub_{_uuid.uuid4().hex[:12]}",
    }
    with sync_session() as session:
        session.execute(
            insert(Subscription)
            .values(
                id=_uuid.uuid4(),
                organization_id=_uuid.UUID(organization_id),
                cancel_at_period_end=False,
                trial_used=False,
                **values,
            )
            .on_conflict_do_update(index_elements=[Subscription.organization_id], set_=values)
        )
