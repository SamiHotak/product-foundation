"""In-memory fakes (no Postgres, Redis, mail server or Google)."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from app.models.job import Job, JobStatus


class FakeJobStore:
    """Implements app.repositories.jobs.JobStore in memory."""

    def __init__(self) -> None:
        self.jobs: dict[uuid.UUID, Job] = {}
        self.commits = 0

    async def create(
        self,
        *,
        kind: str,
        params: dict[str, Any],
        organization_id: uuid.UUID,
        created_by_id: uuid.UUID | None,
    ) -> Job:
        # Strictly increasing timestamps, so ordering is deterministic.
        now = datetime.now(UTC) + timedelta(microseconds=len(self.jobs))
        job = Job(
            id=uuid.uuid4(),
            organization_id=organization_id,
            created_by_id=created_by_id,
            kind=kind,
            status=JobStatus.QUEUED,
            progress=0,
            message="Waiting for a worker",
            params=params,
            result=None,
            error=None,
            attempts=0,
            created_at=now,
            updated_at=now,
            started_at=None,
            finished_at=None,
        )
        self.jobs[job.id] = job
        return job

    @staticmethod
    def _visible(job: Job, viewer_id: uuid.UUID | None) -> bool:
        from app.workers.registry import PRIVATE_JOB_KINDS

        return job.kind not in PRIVATE_JOB_KINDS or (
            viewer_id is not None and job.created_by_id == viewer_id
        )

    async def get(
        self, job_id: uuid.UUID, *, organization_id: uuid.UUID, viewer_id: uuid.UUID | None
    ) -> Job | None:
        job = self.jobs.get(job_id)
        if job is None or job.organization_id != organization_id:
            return None
        return job if self._visible(job, viewer_id) else None

    async def list_recent(
        self, *, organization_id: uuid.UUID, viewer_id: uuid.UUID | None, limit: int
    ) -> list[Job]:
        mine = [
            j
            for j in self.jobs.values()
            if j.organization_id == organization_id and self._visible(j, viewer_id)
        ]
        return sorted(mine, key=lambda j: j.created_at, reverse=True)[:limit]

    async def mark_failed(self, job: Job, error: str) -> None:
        job.status = JobStatus.FAILED
        job.error = error
        job.finished_at = datetime.now(UTC)

    async def commit(self) -> None:
        self.commits += 1


class FakeDispatcher:
    """Records dispatched jobs; can simulate a queue outage."""

    def __init__(self, *, fail: bool = False) -> None:
        self.sent: list[Job] = []
        self.fail = fail
        self.commits_seen: list[int] = []
        self.store: FakeJobStore | None = None

    async def __call__(self, job: Job) -> None:
        if self.store is not None:
            self.commits_seen.append(self.store.commits)
        if self.fail:
            raise ConnectionError("redis://:secret@10.0.0.9:6379 refused")
        self.sent.append(job)


class FakeReporter:
    """Records every status call, like the jobs table would."""

    def __init__(self) -> None:
        self.events: list[tuple[str, Any]] = []

    def started(self) -> None:
        self.events.append(("started", None))

    def progress(self, percent: int, message: str | None = None) -> None:
        self.events.append(("progress", (percent, message)))

    def retrying(self, message: str) -> None:
        self.events.append(("retrying", message))

    def succeeded(self, result: dict[str, Any] | None) -> None:
        self.events.append(("succeeded", result))

    def failed(self, error: str) -> None:
        self.events.append(("failed", error))

    def names(self) -> list[str]:
        return [name for name, _ in self.events]


class FakeEmailSender:
    """Records emails instead of sending them."""

    def __init__(self) -> None:
        from app.services.email import EmailMessage

        self.sent: list[EmailMessage] = []

    async def send(self, message: Any) -> None:
        self.sent.append(message)

    def last_to(self, email: str) -> Any:
        found = [m for m in self.sent if m.to.lower() == email.lower()]
        assert found, f"no email to {email}"
        return found[-1]

    def link_token(self, email: str) -> str:
        """The token from the link in the newest email to this address."""
        import re

        match = re.search(r"token=([A-Za-z0-9_-]+)", self.last_to(email).text)
        assert match, "no token link in email"
        return match.group(1)


class FakeGoogleClient:
    """Pretends to be Google. Set `profile` (or `error`) before the callback."""

    def __init__(self) -> None:
        from app.services.google_oauth import GoogleProfile

        self.profile: GoogleProfile | None = None
        self.error: Exception | None = None
        self.last_verifier: str | None = None

    def authorize_url(self, *, state: str, code_challenge: str, redirect_uri: str) -> str:
        return f"https://accounts.example/auth?state={state}&challenge={code_challenge}"

    async def fetch_profile(self, *, code: str, code_verifier: str, redirect_uri: str) -> Any:
        self.last_verifier = code_verifier
        if self.error:
            raise self.error
        assert self.profile is not None
        return self.profile


class FakeGateway:
    """Pretends to be Stripe. Holds subscriptions that tests change, and records calls."""

    kind = "stripe"

    def __init__(self, prefix: str = "foundation") -> None:
        from app.services.stripe_gateway import SubscriptionSnapshot

        self.prefix = prefix
        self.customers: list[dict[str, Any]] = []
        self.checkouts: list[dict[str, Any]] = []
        self.portals: list[dict[str, Any]] = []
        self.subscriptions: dict[str, SubscriptionSnapshot] = {}
        self.expired: list[str] = []
        self.cancelled: list[str] = []
        self.deleted_customers: list[str] = []
        self.fail: Exception | None = None  # raised by every API call when set
        self.delete_error: Exception | None = None
        self.on_get: Any = None  # called with the id before get_subscription answers

    def _check(self) -> None:
        if self.fail is not None:
            raise self.fail

    async def create_customer(self, *, organization_id: uuid.UUID, name: str, email: str) -> str:
        self._check()
        customer_id = f"cus_test_{len(self.customers) + 1}_{uuid.uuid4().hex[:6]}"
        self.customers.append(
            {"id": customer_id, "organization_id": organization_id, "name": name, "email": email}
        )
        return customer_id

    async def create_checkout(self, **kwargs: Any) -> Any:
        from app.services.stripe_gateway import CheckoutSession

        self._check()
        self.checkouts.append(kwargs)
        n = len(self.checkouts)
        return CheckoutSession(id=f"cs_test_{n}", url=f"https://checkout.stripe.test/c/{n}")

    async def expire_checkout(self, session_id: str) -> None:
        self._check()
        self.expired.append(session_id)

    async def create_portal(self, *, customer_id: str, return_url: str) -> str:
        self._check()
        self.portals.append({"customer_id": customer_id, "return_url": return_url})
        return f"https://billing.stripe.test/p/{customer_id}"

    async def get_subscription(self, subscription_id: str) -> Any:
        self._check()
        if self.on_get is not None:
            self.on_get(subscription_id)
        return self.subscriptions.get(subscription_id)

    async def live_subscriptions(self, customer_id: str) -> list[Any]:
        from app.models.billing import LIVE_STATUSES

        self._check()
        return [
            s
            for s in self.subscriptions.values()
            if s.customer_id == customer_id and s.status in LIVE_STATUSES
        ]

    async def cancel_subscription(self, subscription_id: str) -> None:
        from dataclasses import replace

        self._check()
        self.cancelled.append(subscription_id)
        if subscription_id in self.subscriptions:
            old = self.subscriptions[subscription_id]
            self.subscriptions[subscription_id] = replace(old, status="canceled")

    def parse_event(self, payload: bytes, signature: str | None) -> Any:
        """Accepts JSON events signed with the literal signature "valid"."""
        import json

        from app.services.stripe_gateway import InvalidWebhookError, WebhookEvent

        if signature != "valid":
            raise InvalidWebhookError("Invalid webhook signature.")
        body = json.loads(payload)
        return WebhookEvent(id=body["id"], type=body["type"], data=body["data"]["object"])

    def delete_customer(self, customer_id: str) -> None:
        if self.delete_error is not None:
            raise self.delete_error
        self.deleted_customers.append(customer_id)

    # --- helpers for tests ------------------------------------------------------------

    def set_subscription(
        self,
        customer_id: str,
        *,
        sub_id: str = "sub_1",
        status: str = "active",
        plan_id: str | None = "pro",
        interval: str = "month",
        cancel_at_period_end: bool = False,
        trial_days: int = 0,
    ) -> Any:
        """Make Stripe "have" this subscription (what a webhook would then read)."""
        from app.services.stripe_gateway import SubscriptionSnapshot

        now = datetime.now(UTC)
        snap = SubscriptionSnapshot(
            id=sub_id,
            customer_id=customer_id,
            status=status,
            plan_id=plan_id,
            interval=interval,
            current_period_end=now + timedelta(days=30),
            cancel_at_period_end=cancel_at_period_end,
            trial_end=now + timedelta(days=trial_days) if trial_days else None,
        )
        self.subscriptions[sub_id] = snap
        return snap
