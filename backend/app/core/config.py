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

    @model_validator(mode="after")
    def _fill_defaults_and_check(self) -> "Settings":
        if self.celery_broker_url is None:
            self.celery_broker_url = self.redis_url
        if self.celery_result_backend is None:
            self.celery_result_backend = self.redis_url
        if (
            self.environment is Environment.PRODUCTION
            and self.secret_key.get_secret_value() == DEV_SECRET_KEY
        ):
            raise ValueError("SECRET_KEY must be set to a strong random value in production.")
        return self

    @property
    def is_production(self) -> bool:
        """True when running in production."""
        return self.environment is Environment.PRODUCTION


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings instance (use as a FastAPI dependency)."""
    return Settings()
