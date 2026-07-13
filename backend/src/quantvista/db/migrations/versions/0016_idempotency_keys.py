"""0016 idempotency_keys: generic idempotent-mutation store (QV-052)

Backs the ``Idempotency-Key`` header on mutating endpoints (04 §1): the first request stores its
``(response_status, response_body)`` under ``(tenant_id, idempotency_key)``; a replay returns it
verbatim, and the same key reused with a *different* request (``request_fingerprint`` mismatch) is
a client error (409). Tenant-scoped and RLS-enforced like every table carrying ``tenant_id``.

First wired into ``POST /portfolios``; reusable by future mutations (alerts/screens/backtests).

Revision ID: 0016
Revises: 0015
Create Date: 2026-07-13
"""

from __future__ import annotations

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def _enable_rls(table: str) -> None:
    """ENABLE + FORCE RLS and add the standard tenant-isolation policy."""
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
    op.execute(
        f"CREATE POLICY {table}_isolation ON {table} "
        f"USING (tenant_id = app_current_tenant()) "
        f"WITH CHECK (tenant_id = app_current_tenant());"
    )


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE idempotency_keys (
            id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            idempotency_key     text NOT NULL,
            request_fingerprint text NOT NULL,
            response_status     int  NOT NULL,
            response_body       jsonb NOT NULL,
            created_at          timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, idempotency_key)
        );
        CREATE INDEX ix_idempotency_keys_tenant_id ON idempotency_keys (tenant_id);
        """
    )
    _enable_rls("idempotency_keys")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS idempotency_keys CASCADE;")
