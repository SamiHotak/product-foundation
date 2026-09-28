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
        return self

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
