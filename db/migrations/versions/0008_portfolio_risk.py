"""0008 portfolio & risk (tenant-scoped, RLS)

portfolios, portfolio_positions, optimization_runs, risk_snapshots.
All carry tenant_id and are protected by RLS via app_current_tenant().

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-14
"""

from __future__ import annotations

from alembic import op

revision = "0008"
down_revision = "0007"
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
        CREATE TABLE portfolios (
            id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id     uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            user_id       uuid NOT NULL REFERENCES users(id),
            name          text NOT NULL,
            benchmark     text NOT NULL DEFAULT 'NIFTY200_TRI',
            base_currency char(3) NOT NULL DEFAULT 'INR',
            created_at    timestamptz NOT NULL DEFAULT now(),
            updated_at    timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_portfolios_tenant_id ON portfolios (tenant_id);
        """
    )

    op.execute(
        """
        CREATE TABLE portfolio_positions (
            id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id     uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            portfolio_id  uuid NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
            stock_id      uuid NOT NULL REFERENCES stocks(id),
            weight        numeric(9, 6),
            target_weight numeric(9, 6),
            shares        numeric(20, 6),
            avg_cost      numeric(18, 4),
            created_at    timestamptz NOT NULL DEFAULT now(),
            updated_at    timestamptz NOT NULL DEFAULT now(),
            UNIQUE (portfolio_id, stock_id)
        );
        CREATE INDEX ix_portfolio_positions_tenant_id ON portfolio_positions (tenant_id);
        CREATE INDEX ix_portfolio_positions_portfolio_id ON portfolio_positions (portfolio_id);
        """
    )

    op.execute(
        """
        CREATE TABLE optimization_runs (
            id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id    uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            portfolio_id uuid NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
            method       text NOT NULL
                         CHECK (method IN ('mean_variance','risk_parity','black_litterman','hrp')),
            objective    text,
            constraints  jsonb NOT NULL DEFAULT '{}'::jsonb,
            status       text NOT NULL DEFAULT 'succeeded'
                         CHECK (status IN ('succeeded','infeasible','failed')),
            result       jsonb,                        -- weights + expected return/vol
            created_at   timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_optimization_runs_tenant_id ON optimization_runs (tenant_id);
        """
    )

    op.execute(
        """
        CREATE TABLE risk_snapshots (
            id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id     uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            portfolio_id  uuid NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
            as_of_date    date NOT NULL,
            beta          numeric(18, 6),
            volatility    numeric(18, 6),
            max_drawdown  numeric(18, 6),
            sharpe        numeric(18, 6),
            sortino       numeric(18, 6),
            hhi           numeric(9, 6),               -- concentration
            sector_exposure jsonb,
            created_at    timestamptz NOT NULL DEFAULT now(),
            UNIQUE (portfolio_id, as_of_date)
        );
        CREATE INDEX ix_risk_snapshots_tenant_id ON risk_snapshots (tenant_id);
        """
    )

    for tbl in ("portfolios", "portfolio_positions"):
        op.execute(
            f"CREATE TRIGGER trg_{tbl}_updated_at BEFORE UPDATE ON {tbl} "
            f"FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
        )

    for tbl in ("portfolios", "portfolio_positions", "optimization_runs", "risk_snapshots"):
        _enable_rls(tbl)


def downgrade() -> None:
    for tbl in ("risk_snapshots", "optimization_runs", "portfolio_positions", "portfolios"):
        op.execute(f"DROP TABLE IF EXISTS {tbl} CASCADE;")
