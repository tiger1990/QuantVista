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


@lru_cache
def get_settings() -> Settings:
    """Process-wide cached settings. Call ``get_settings.cache_clear()`` in tests."""
    return Settings()
