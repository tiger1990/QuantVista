"""Tests for env-driven settings (quantvista.core.config)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from quantvista.core.config import Settings, get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_settings_have_local_defaults() -> None:
    # Arrange / Act — no env vars or .env present in the test environment
    settings = Settings()
    # Assert
    assert settings.app_env == "local"
    assert settings.database_url.startswith("postgresql+psycopg://")
    assert settings.redis_url.startswith("redis://")


def test_settings_read_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@db:5432/x")
    monkeypatch.setenv("REDIS_URL", "redis://cache:6379/2")
    # Act
    settings = get_settings()
    # Assert
    assert settings.app_env == "test"
    assert settings.database_url.endswith("/x")
    assert settings.redis_url == "redis://cache:6379/2"


def test_get_settings_is_cached() -> None:
    # Arrange / Act / Assert
    assert get_settings() is get_settings()
