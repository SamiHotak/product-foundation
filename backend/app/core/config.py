"""Application settings, loaded only from environment variables (and an optional .env file).

Every setting has a safe development default, except secrets in production:
the validator refuses to start in production with the dev secret key.
"""

import re
from enum import StrEnum
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_SECRET_KEY = "dev-only-secret-change-me"  # noqa: S105 - explicit dev placeholder


class Environment(StrEnum):
    """Where the app is running."""

    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """All runtime configuration. Names map 1:1 to env vars (case-insensitive)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # General
    app_name: str = "Product Foundation"
    environment: Environment = Environment.DEVELOPMENT
    secret_key: SecretStr = SecretStr(DEV_SECRET_KEY)
    api_prefix: str = "/api"

    # Logging: "json" for machines (production), "console" for humans (dev).
    log_level: str = "INFO"
    log_format: str = "console"

    # Databases and queues
    database_url: str = "postgresql+psycopg://app:app@localhost:5432/app"
    # Production only: a second, more powerful database user that may create and change
    # tables. Only migrations use it (`alembic`, `python -m app.scripts.db_roles`). The running
    # app connects with DATABASE_URL, a limited user. Empty = migrations use DATABASE_URL (dev).
    migration_database_url: SecretStr | None = None  # SecretStr: never printed by accident
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str | None = None  # defaults to redis_url
    celery_result_backend: str | None = None  # defaults to redis_url

    # HTTP
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    # Timeouts for health checks (seconds)
    health_check_timeout: float = 2.0

    # Public URL of the web app (links in emails, Google redirect, CSRF origin check).
    app_url: str = "http://localhost:3000"

    # Sessions (server-side, in Postgres; the browser only holds a random id in a cookie).
    session_cookie_name: str = "session"
    session_days: int = 30
    session_cookie_secure: bool | None = None  # default: True in production

    # Email. "smtp": any SMTP server (Mailpit locally). "resend" / "postmark": their HTTP API
    # with EMAIL_API_KEY (better errors and delivery logs than SMTP). See docs/BILLING.md.
    email_provider: Literal["smtp", "resend", "postmark"] = "smtp"
    email_api_key: SecretStr | None = None
    email_reply_to: str | None = None  # e.g. support@your-domain.com
    # Shown in the footer of every email (B2B: who sends it). Empty = only the product name.
    email_footer_address: str = ""
    email_brand_color: str = "#244ba6"  # buttons in emails; keep close to the product accent
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_starttls: bool = False
    email_from: str = "Foundation <no-reply@localhost>"

    # Token lifetimes
    email_verification_hours: int = 48
    password_reset_minutes: int = 60

    # Brute-force protection
    login_max_failures: int = 5  # per email, then locked for login_lock_minutes
    login_lock_minutes: int = 15
    auth_requests_per_minute_per_ip: int = 20

    # Google sign-in. Leave empty to hide the button.
    google_client_id: str | None = None
    google_client_secret: SecretStr | None = None

    # Invites
    invite_days: int = 7  # how long an invite link works
    invites_per_org_per_hour: int = 30  # stops a workspace from being used to spam inboxes

    # API keys (public REST API). Keys look like "<prefix>_<random>".
    api_key_prefix: str = "pf"
    api_key_requests_per_minute: int = 600

    # GDPR: deleting an account or workspace waits this many days (can be cancelled).
    deletion_grace_days: int = 14
    export_retention_days: int = 7  # data export ZIPs are deleted after this
    audit_retention_days: int = 365  # audit log entries older than this are deleted

    # Cookie-less website analytics (Plausible or Umami). "none" = off (the default).
    # The browser sends page views to our own API; the API forwards them. So there is no
    # third-party script on the page and nothing is stored in the visitor's browser.
    analytics_provider: Literal["none", "plausible", "umami"] = "none"
    analytics_host: str = ""  # e.g. https://plausible.io or https://cloud.umami.is
    analytics_site: str = ""  # Plausible: your domain. Umami: the website id.
    analytics_events_per_minute_per_ip: int = 120

    # Billing (Stripe). Leave STRIPE_SECRET_KEY empty to switch paid plans off.
    # Test mode keys start with sk_test_. Put them in backend/.env (never committed).
    stripe_secret_key: SecretStr | None = None
    stripe_webhook_secret: SecretStr | None = None
    # Prefix of the Stripe product ids and price lookup keys ("foundation_pro_month").
    # Every product needs its OWN prefix, because your products can share one Stripe account.
    stripe_prefix: str = "foundation"
    # Stripe Tax calculates VAT at checkout (Stripe charges a fee; register your tax IDs
    # in the Stripe dashboard first). Off: prices are charged as configured in plans.py.
    stripe_automatic_tax: bool = False
    # Local development and e2e tests only: a pretend checkout and portal (no Stripe account
    # needed) and POST /api/billing/dev/set-plan. Refused in production.
    billing_dev_tools: bool = False

    # File storage: any S3-compatible service. Locally SeaweedFS in Docker, in production
    # Hetzner Object Storage. Empty S3_ENDPOINT = file uploads are switched off.
    s3_endpoint: str = ""  # e.g. http://s3:8333 or https://fsn1.your-objectstorage.com
    s3_region: str = "us-east-1"  # Hetzner: fsn1, nbg1 or hel1
    s3_bucket: str = "foundation-files"
    s3_access_key: str = ""
    s3_secret_key: SecretStr | None = None
    # The address BROWSERS use for uploads and downloads. Empty = the same as S3_ENDPOINT.
    # Locally "/storage": the Next.js server forwards /storage/... to S3_ENDPOINT, so the
    # browser never needs to reach the S3 container (see frontend/next.config.ts).
    s3_public_url: str = ""
    files_max_bytes: int = 25 * 1024 * 1024  # one file (25 MB)
    files_upload_minutes: int = 15  # how long an upload link works
    files_download_seconds: int = 300  # how long a download link works
    # Virus scanning with ClamAV (clamd, TCP). Empty = no scan. See docs/FILES_AND_AI.md.
    clamav_host: str = ""
    clamav_port: int = 3310

    # LLM gateway (app/llm/). One place for every AI call. See docs/FILES_AND_AI.md.
    # Kill switch: LLM_ENABLED=false stops every AI call at once (admins also have a switch
    # in the app that works without a restart).
    llm_enabled: bool = True
    openai_api_key: SecretStr | None = None
    # e.g. https://eu.api.openai.com/v1 for EU data residency (needs an eligible project).
    openai_base_url: str | None = None
    # Local development and e2e tests only: a pretend model when there is no API key.
    # It returns fixed answers and costs nothing. Refused in production.
    llm_dev_fake: bool = False
    # A different model for a task, e.g. LLM_MODELS='{"summarize": "gpt-6.1-sol"}'.
    llm_models: dict[str, str] = Field(default_factory=dict)
    # Also send prompts and answers to Langfuse. Off by default (privacy by default): then
    # Langfuse only gets the task, model, tokens, cost, timing and error codes.
    llm_trace_content: bool = False
    # Langfuse (LLM traces and costs). Empty keys = no tracing.
    langfuse_host: str = (
        "https://cloud.langfuse.com"  # EU region; US: https://us.cloud.langfuse.com
    )
    langfuse_public_key: str = ""
    langfuse_secret_key: SecretStr | None = None

    # Demo mode: the "Try the demo" button signs visitors into a shared, read-mostly
    # demo workspace (make seed creates it; a nightly task resets it).
    demo_enabled: bool = False
    demo_email: str = "demo@example.com"
    # AI summaries per visitor (IP) and hour in the shared demo (it may only use the samples).
    demo_ai_per_hour: int = Field(default=10, ge=1)

    # Sentry (error reports). Empty DSN = off. Personal data is NOT sent (no cookies, no
    # request bodies, no user email); see app/core/sentry.py. SENTRY_RELEASE is set by the
    # deploy (the image tag), so an error shows which version caused it.
    sentry_dsn: str = ""
    sentry_release: str = ""
    sentry_traces_sample_rate: float = Field(default=0.0, ge=0.0, le=1.0)

    # Admins (users with is_superuser) can view the app as another user for support.
    impersonation_minutes: int = 60

    @model_validator(mode="after")
    def _fill_defaults_and_check(self) -> "Settings":
        if self.celery_broker_url is None:
            self.celery_broker_url = self.redis_url
        if self.celery_result_backend is None:
            self.celery_result_backend = self.redis_url
        if self.session_cookie_secure is None:
            self.session_cookie_secure = self.environment is Environment.PRODUCTION
        self.app_url = self.app_url.rstrip("/")
        self.analytics_host = self.analytics_host.strip().rstrip("/")
        if self.analytics_provider != "none" and not (self.analytics_host and self.analytics_site):
            raise ValueError("ANALYTICS_HOST and ANALYTICS_SITE are needed when analytics is on.")
        if self.analytics_host and not self.analytics_host.startswith(("https://", "http://")):
            raise ValueError("ANALYTICS_HOST must start with https://")
        if not re.fullmatch(r"[a-z][a-z0-9_]{1,30}", self.stripe_prefix):
            raise ValueError("STRIPE_PREFIX: 2-31 characters, a-z, 0-9 and _ only.")
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", self.email_brand_color):
            raise ValueError("EMAIL_BRAND_COLOR must look like #244ba6.")
        if self.email_provider != "smtp" and not self.email_api_key:
            raise ValueError("EMAIL_API_KEY is needed when EMAIL_PROVIDER is resend or postmark.")
        if self.is_production and self.billing_dev_tools:
            raise ValueError("BILLING_DEV_TOOLS must be off in production.")
        if (
            self.billing_dev_tools
            and self.stripe_secret_key
            and (self.stripe_secret_key.get_secret_value().startswith(("sk_live_", "rk_live_")))
        ):
            # set-plan would hand out paid plans for free next to real payments.
            raise ValueError("BILLING_DEV_TOOLS can't be on with a LIVE Stripe key.")
        if self.is_production and self.stripe_secret_key and not self.stripe_webhook_secret:
            raise ValueError("STRIPE_WEBHOOK_SECRET is needed when Stripe is on.")
        if (
            self.environment is Environment.PRODUCTION
            and self.secret_key.get_secret_value() == DEV_SECRET_KEY
        ):
            raise ValueError("SECRET_KEY must be set to a strong random value in production.")
        self.s3_endpoint = self.s3_endpoint.strip().rstrip("/")
        self.s3_public_url = self.s3_public_url.strip().rstrip("/")
        if self.s3_endpoint:
            if not self.s3_endpoint.startswith(("https://", "http://")):
                raise ValueError("S3_ENDPOINT must start with https:// (or http:// locally).")
            if not (self.s3_access_key and self.s3_secret_key):
                raise ValueError("S3_ACCESS_KEY and S3_SECRET_KEY are needed with S3_ENDPOINT.")
            if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", self.s3_bucket):
                raise ValueError("S3_BUCKET: 3-63 characters, a-z, 0-9, dots and dashes.")
        if self.s3_public_url and not self.s3_public_url.startswith(("https://", "http://", "/")):
            raise ValueError("S3_PUBLIC_URL must be a full URL or a path like /storage.")
        if not 1024 <= self.files_max_bytes <= 5 * 1024**3:
            raise ValueError("FILES_MAX_BYTES must be between 1 KB and 5 GB.")
        if self.is_production and self.llm_dev_fake:
            raise ValueError("LLM_DEV_FAKE must be off in production.")
        self.sentry_dsn = self.sentry_dsn.strip()
        if self.sentry_dsn and not self.sentry_dsn.startswith("https://"):
            raise ValueError("SENTRY_DSN must start with https://")
        self.langfuse_host = self.langfuse_host.strip().rstrip("/")
        if self.langfuse_public_key and not self.langfuse_secret_key:
            raise ValueError("LANGFUSE_SECRET_KEY is needed with LANGFUSE_PUBLIC_KEY.")
        return self

    @property
    def files_enabled(self) -> bool:
        """True when file storage is configured."""
        return bool(self.s3_endpoint)

    @property
    def openai_enabled(self) -> bool:
        """True when a real OpenAI key is configured."""
        return bool(self.openai_api_key and self.openai_api_key.get_secret_value())

    @property
    def langfuse_enabled(self) -> bool:
        """True when LLM traces are sent to Langfuse."""
        return bool(self.langfuse_public_key and self.langfuse_secret_key)

    @property
    def google_enabled(self) -> bool:
        """True when Google sign-in is configured."""
        return bool(self.google_client_id and self.google_client_secret)

    @property
    def stripe_enabled(self) -> bool:
        """True when real Stripe payments are configured."""
        return bool(self.stripe_secret_key and self.stripe_secret_key.get_secret_value())

    @property
    def allowed_origins(self) -> set[str]:
        """Origins allowed to send state-changing requests with the session cookie."""
        return {self.app_url, *(o.rstrip("/") for o in self.cors_origins)}

    @property
    def is_production(self) -> bool:
        """True when running in production."""
        return self.environment is Environment.PRODUCTION


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings instance (use as a FastAPI dependency)."""
    return Settings()
