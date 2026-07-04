"""Application configuration — env-driven via pydantic-settings.

One ``Settings`` object backs all three runtime roles (api/worker/beat). No secrets in
source: values come from the environment (`.env` locally, Secrets Manager/SSM in cloud).
The defaults here are **local-dev conveniences only** (MinIO's documented defaults) and
are overridden by env in every real environment.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "local"
    # App connection: the NON-superuser role (RLS enforced). Tenant-table access.
    database_url: str = (
        "postgresql+psycopg://quantvista_app:quantvista_app@localhost:5432/quantvista"
    )
    # Admin/privileged connection: migrations + reference/global-table writes by jobs.
    admin_database_url: str = "postgresql+psycopg://quantvista:quantvista@localhost:5432/quantvista"
    redis_url: str = "redis://localhost:6379/0"
    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "quantvista-local"

    # Auth (QV-006). jwt_secret MUST be overridden in any non-local environment.
    jwt_secret: str = "dev-insecure-secret-change-me-in-non-local-environments"
    jwt_algorithm: str = "HS256"
    access_token_ttl_seconds: int = 900  # ~15 min
    refresh_token_ttl_seconds: int = 2_592_000  # 30 days
    cookie_secure: bool = True
    cookie_samesite: str = "lax"
    refresh_cookie_name: str = "qv_refresh"

    # Observability (QV-009). All backend-optional: unset endpoint/DSN means the
    # corresponding exporter/SDK is never wired, so api/worker boot cleanly with no
    # collector, Sentry, or Grafana present (local, CI, and the no-creds dev box).
    log_level: str = "INFO"
    log_json: bool = False  # human console locally; JSON in cloud (log_json=true)
    otel_exporter_otlp_endpoint: str | None = None  # e.g. http://collector:4317
    otel_service_name: str | None = None  # defaults to quantvista-<role> when unset
    sentry_dsn: str | None = None  # unset → sentry_sdk.init is skipped entirely
    sentry_traces_sample_rate: float = 0.0
    metrics_enabled: bool = True
    worker_metrics_port: int = 9100  # prometheus_client HTTP server for the worker role

    # Event bus backend (QV-024): in_process | redis_streams | kafka. Toggle by traffic —
    # in_process for dev/idle, redis_streams / kafka in production. Same IEventBus + envelope.
    event_bus_backend: str = "in_process"
    event_bus_group: str = "quantvista"  # consumer-group name (redis_streams / kafka)
    kafka_bootstrap_servers: str = "localhost:9092"


@lru_cache
def get_settings() -> Settings:
    """Process-wide cached settings. Call ``get_settings.cache_clear()`` in tests."""
    return Settings()
