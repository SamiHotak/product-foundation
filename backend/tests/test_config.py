"""Settings tests."""

import pytest
from pydantic import ValidationError

from app.core.config import Environment, Settings


def test_celery_urls_default_to_redis_url() -> None:
    s = Settings(_env_file=None, redis_url="redis://cache:6379/1")
    assert s.celery_broker_url == "redis://cache:6379/1"
    assert s.celery_result_backend == "redis://cache:6379/1"


def test_production_refuses_dev_secret_key() -> None:
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        Settings(_env_file=None, environment=Environment.PRODUCTION)


def test_settings_read_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_NAME", "AskDocs")
    monkeypatch.setenv("CORS_ORIGINS", '["https://askdocs.example"]')
    s = Settings(_env_file=None)
    assert s.app_name == "AskDocs"
    assert s.cors_origins == ["https://askdocs.example"]


def test_secret_key_not_shown_in_repr() -> None:
    s = Settings(_env_file=None, secret_key="super-secret-value")
    assert "super-secret-value" not in repr(s)
