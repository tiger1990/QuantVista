"""0003 reference & market data (global, no tenant_id / no RLS)

markets, stocks (survivorship-aware), index_constituents (PIT membership),
corporate_actions, macro_series.

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-14
"""

from __future__ import annotations

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- markets (market-agnostic core, D2) ----
    op.execute(
        """
        CREATE TABLE markets (
            id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            code              text NOT NULL UNIQUE,          -- 'NSE'
            name              text NOT NULL,
            country           text NOT NULL,                 -- 'IN'
            currency          char(3) NOT NULL,              -- 'INR'
            timezone          text NOT NULL,                 -- 'Asia/Kolkata'
            trading_calendar  text,                          -- calendar ref/key
            is_active         boolean NOT NULL DEFAULT true,
            created_at        timestamptz NOT NULL DEFAULT now()
        );
        """
    )

    # ---- stocks ----
    op.execute(
        """
        CREATE TABLE stocks (
            id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            market_id         uuid NOT NULL REFERENCES markets(id),
            symbol            text NOT NULL,
            isin              text,
            company_name      text NOT NULL,
            sector            text,
            industry          text,
            market_cap_bucket text CHECK (market_cap_bucket IN ('large','mid','small','micro')),
            listed_on         date,
            delisted_on       date,                          -- survivorship-free history (03 §5)
            is_active         boolean NOT NULL DEFAULT true,
            created_at        timestamptz NOT NULL DEFAULT now(),
            updated_at        timestamptz NOT NULL DEFAULT now(),
            UNIQUE (market_id, symbol)
        );
        CREATE INDEX ix_stocks_isin ON stocks (isin);
        CREATE INDEX ix_stocks_sector ON stocks (sector);
        CREATE INDEX ix_stocks_is_active ON stocks (is_active) WHERE is_active;
        """
    )

    # ---- index_constituents (point-in-time membership + weights) ----
    op.execute(
        """
        CREATE TABLE index_constituents (
            id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            index_code     text NOT NULL,                   -- 'NIFTY200'
            stock_id       uuid NOT NULL REFERENCES stocks(id),
            effective_from date NOT NULL,
            effective_to   date,                            -- NULL = current member
            weight         numeric(9, 6),
            CHECK (effective_to IS NULL OR effective_to > effective_from)
        );
        CREATE INDEX ix_index_constituents_index_code_stock_id
            ON index_constituents (index_code, stock_id);
        -- One open membership row per (index, stock).
        CREATE UNIQUE INDEX uq_index_constituents_open
            ON index_constituents (index_code, stock_id)
            WHERE effective_to IS NULL;
        """
    )

    # ---- corporate_actions (drive adj_close) ----
    op.execute(
        """
        CREATE TABLE corporate_actions (
            id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            stock_id        uuid NOT NULL REFERENCES stocks(id),
            ex_date         date NOT NULL,
            action_type     text NOT NULL
                            CHECK (action_type IN ('split','bonus','dividend','rights','merger')),
            ratio_or_amount numeric(18, 6),
            details         jsonb NOT NULL DEFAULT '{}'::jsonb,
            source          text,
            ingested_at     timestamptz NOT NULL DEFAULT now(),
            UNIQUE (stock_id, ex_date, action_type)
        );
        CREATE INDEX ix_corporate_actions_stock_id_ex_date
            ON corporate_actions (stock_id, ex_date);
        """
    )

    # ---- macro_series (generic time series: rates, inflation, GDP) ----
    op.execute(
        """
        CREATE TABLE macro_series (
            id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            series_code text NOT NULL,
            date        date NOT NULL,
            value       numeric(20, 6),
            source      text,
            ingested_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (series_code, date)
        );
        """
    )

    op.execute(
        "CREATE TRIGGER trg_stocks_updated_at BEFORE UPDATE ON stocks "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
    )


def downgrade() -> None:
    for tbl in ("macro_series", "corporate_actions", "index_constituents", "stocks", "markets"):
        op.execute(f"DROP TABLE IF EXISTS {tbl} CASCADE;")
