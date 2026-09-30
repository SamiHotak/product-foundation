"""Admin schemas (/admin, app admins only)."""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class AdminOverview(BaseModel):
    """Headline numbers of the whole app."""

    users: int
    workspaces: int
    paid_workspaces: int
    failed_jobs_7d: int = Field(description="Jobs that failed for good in the last 7 days.")
    ai_requests_month: int
    ai_cost_usd_month: float
    storage_bytes: int
    ai_paused: bool = Field(description="The AI kill switch is on.")
    ai_provider: str = Field(description='"openai", "fake" (dev) or "none".')
    month: date


class AdminOrganization(BaseModel):
    """One workspace."""

    id: uuid.UUID
    name: str
    created_at: datetime
    owner_email: str | None
    members: int
    plan_id: str | None = Field(description="The paid plan, or null (free).")
    subscription_status: str | None
    storage_bytes: int
    jobs_month: int
    ai_requests_month: int
    ai_cost_usd_month: float
    deletion_scheduled_at: datetime | None


class AdminOrganizationList(BaseModel):
    """Workspaces, newest first."""

    items: list[AdminOrganization]


class AdminUser(BaseModel):
    """One user."""

    id: uuid.UUID
    name: str
    email: str
    email_verified: bool
    is_superuser: bool
    is_demo: bool
    is_active: bool
    workspaces: int
    created_at: datetime
    last_login_at: datetime | None
    deletion_scheduled_at: datetime | None


class AdminUserList(BaseModel):
    """Users, newest first."""

    items: list[AdminUser]


class AdminSubscription(BaseModel):
    """One billing row (mirror of Stripe)."""

    organization_id: uuid.UUID
    organization_name: str
    plan_id: str | None
    status: str | None
    interval: str | None
    current_period_end: datetime | None
    cancel_at_period_end: bool
    trial_end: datetime | None
    stripe_customer_id: str | None
    stripe_subscription_id: str | None
    updated_at: datetime


class AdminSubscriptionList(BaseModel):
    """Paid ones first."""

    items: list[AdminSubscription]


class AdminAiUsageRow(BaseModel):
    """AI use of one workspace with one task and model in the month."""

    organization_id: uuid.UUID
    organization_name: str
    task: str
    model: str
    requests: int
    failed: int
    input_tokens: int
    output_tokens: int
    cost_usd: float


class AdminUsage(BaseModel):
    """AI requests and costs of one month (UTC)."""

    month: date
    rows: list[AdminAiUsageRow]
    total_requests: int
    total_cost_usd: float


class AdminFailedJob(BaseModel):
    """A job that failed for good (the dead-letter list)."""

    id: uuid.UUID
    kind: str
    organization_id: uuid.UUID
    organization_name: str
    started_by: str | None
    error: str | None
    attempts: int
    created_at: datetime
    finished_at: datetime | None


class AdminFailedJobList(BaseModel):
    """Newest first."""

    items: list[AdminFailedJob]


class AiPauseUpdate(BaseModel):
    """Turn the AI kill switch on or off."""

    model_config = ConfigDict(extra="forbid")

    paused: bool


class ImpersonationStopped(BaseModel):
    """Where the browser goes next."""

    restored_admin_session: bool = Field(
        description="True: you are signed in as yourself again. False: sign in again."
    )
