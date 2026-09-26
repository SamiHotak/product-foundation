"""Application settings, loaded only from environment variables (and an optional .env file).

Every setting has a safe development default, except secrets in production:
the validator refuses to start in production with the dev secret key.
"""

from enum import StrEnum
from functools import lru_cache

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

    # Email (Mailpit locally; a real provider in phase 4A).
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

    @model_validator(mode="after")
    def _fill_defaults_and_check(self) -> "Settings":
        if self.celery_broker_url is None:
            self.celery_broker_url = self.redis_url
        if self.celery_result_backend is None:
            self.celery_result_backend = self.redis_url
        if self.session_cookie_secure is None:
            self.session_cookie_secure = self.environment is Environment.PRODUCTION
        self.app_url = self.app_url.rstrip("/")
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
