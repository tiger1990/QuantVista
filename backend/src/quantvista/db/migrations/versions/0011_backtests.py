"""0011 backtests (tenant-scoped, RLS)

Async backtests: spec in, status + metrics + artifact out. Stores spec + model/weights
versions for reproducibility (05 §4).

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-14
"""

from __future__ import annotations

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE backtests (
            id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            user_id         uuid NOT NULL REFERENCES users(id),
            spec            jsonb NOT NULL,           -- universe, rules, range, costs, benchmark
            status          text NOT NULL DEFAULT 'queued'
                            CHECK (status IN ('queued','running','succeeded','failed')),
            started_at      timestamptz,
            finished_at     timestamptz,
            result_ref      text,                     -- object-store key for full result artifact
            metrics         jsonb,                    -- CAGR, vol, Sharpe, maxDD, hit rate, turnover
            model_version   text,
            weights_version text,
            error           text,
            created_at      timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_backtests_tenant_id ON backtests (tenant_id);
        CREATE INDEX ix_backtests_status ON backtests (status);
        """
    )

    op.execute("ALTER TABLE backtests ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE backtests FORCE ROW LEVEL SECURITY;")
    op.execute(
        "CREATE POLICY backtests_isolation ON backtests "
        "USING (tenant_id = app_current_tenant()) "
        "WITH CHECK (tenant_id = app_current_tenant());"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS backtests CASCADE;")
