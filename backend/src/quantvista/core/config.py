"""Application configuration — env-driven via pydantic-settings.

One ``Settings`` object backs all three runtime roles (api/worker/beat). No secrets in
source: values come from the environment (`.env` locally, Secrets Manager/SSM in cloud).
The defaults here are **local-dev conveniences only** (MinIO's documented defaults) and
are overridden by env in every real environment.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
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

    # Macro data (QV-026): FRED API key (free, redistributable). Unset → macro sync can't run.
    fred_api_key: str | None = None

    # News (QV-041): provider-agnostic multi-source ingestion. `news_providers` is the enabled set
    # (comma-separated); the service fans out over those that have a key configured. All free tiers
    # are dev-grade (NewsAPI is development-only) — production needs paid tiers, like yfinance.
    news_providers: str = "newsapi,gnews,marketaux,finnhub"
    # Env names are pinned via aliases where they differ from the field name (user's .env spelling).
    newsapi_org_api_key: str | None = Field(default=None, validation_alias="NEWS_API_ORG_API_KEY")
    gnews_api_key: str | None = None  # env: GNEWS_API_KEY
    marketaux_api_key: str | None = None  # env: MARKETAUX_API_KEY
    finnhub_api_key: str | None = Field(default=None, validation_alias="FINHUB_API_KEY")

    # Sentiment model runtime (QV-044): dev | finbert. `dev` = DevSentiment (lexicon, always-on;
    # runs on x86 macOS 12 + CI). `finbert` = FinBERTSentiment (ProsusAI/finbert via the [finbert]
    # extra) — set only on a capable host running the `nlp` queue worker; writes coexist by
    # model_version, so a dev worker and a finbert worker can score the same corpus independently.
    sentiment_model: str = "dev"

    # Caching (QV-031): Redis cache-aside for scores/rankings, invalidated on ScoresComputed.
    cache_enabled: bool = True  # false → NullCache (dev/tests with no Redis)
    cache_ttl_seconds: int = 3600  # TTL backstop if an invalidation event is ever missed

    # Email delivery (QV-049): plug-and-play provider. `log` = LogEmailSender (dev/CI, no creds).
    # `brevo` = Brevo transactional REST API (300/day free); a later `ses` adds Amazon SES. Only the
    # selected provider's key is needed. `email_from` MUST be a sender verified in the provider.
    email_provider: str = "log"  # log | brevo
    email_from: str = "alerts@quantvista.local"
    email_from_name: str = "QuantVista Alerts"
    brevo_api_key: str | None = None  # env: BREVO_API_KEY (gitignored .env only)
    # Branded HTML alert emails (QV-049 enhancement). `email_logo_url`, when set to a PUBLICLY
    # hosted image, renders as the header logo; unset → a styled "QUANTVISTA" text wordmark (no
    # hosting dependency). `app_base_url` is the CTA link target ("View in QuantVista").
    email_logo_url: str | None = None  # e.g. https://cdn.quantvista.app/logo.png
    app_base_url: str = "http://localhost:3000"


@lru_cache
def get_settings() -> Settings:
    """Process-wide cached settings. Call ``get_settings.cache_clear()`` in tests."""
    return Settings()
