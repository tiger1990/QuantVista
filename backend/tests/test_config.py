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


def test_observability_defaults_are_no_op_safe() -> None:
    # Arrange / Act — no env present
    settings = Settings()
    # Assert — defaults must let api/worker boot with NO observability backend wired
    assert settings.log_level == "INFO"
    assert settings.log_json is False
    assert settings.otel_exporter_otlp_endpoint is None
    assert settings.otel_service_name is None
    assert settings.sentry_dsn is None
    assert settings.sentry_traces_sample_rate == 0.0
    assert settings.metrics_enabled is True
    assert settings.worker_metrics_port == 9100


def test_observability_settings_read_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setenv("LOG_JSON", "true")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4317")
    monkeypatch.setenv("SENTRY_DSN", "https://public@sentry.example/1")
    monkeypatch.setenv("SENTRY_TRACES_SAMPLE_RATE", "0.25")
    monkeypatch.setenv("METRICS_ENABLED", "false")
    # Act
    settings = get_settings()
    # Assert
    assert settings.log_json is True
    assert settings.otel_exporter_otlp_endpoint == "http://collector:4317"
    assert settings.sentry_dsn == "https://public@sentry.example/1"
    assert settings.sentry_traces_sample_rate == 0.25
    assert settings.metrics_enabled is False
