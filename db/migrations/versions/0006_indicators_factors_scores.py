"""0006 technical_indicators, factor_values, scores (partitioned, global)

All three are PARTITION BY RANGE (date) monthly. scores is the read-hot table (cached).
factor_values is the decomposition source of truth (parts sum to composite, 05 §1.2).

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-14
"""

from __future__ import annotations

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def _bootstrap_partitions(parent: str) -> None:
    op.execute(f"CREATE TABLE {parent}_default PARTITION OF {parent} DEFAULT;")
    op.execute(f"SELECT create_month_partition('{parent}', date_trunc('month', now())::date);")
    op.execute(
        f"SELECT create_month_partition('{parent}', "
        f"date_trunc('month', now() + interval '1 month')::date);"
    )


def upgrade() -> None:
    # ---- technical_indicators ----
    op.execute(
        """
        CREATE TABLE technical_indicators (
            id              bigint GENERATED ALWAYS AS IDENTITY,
            stock_id        uuid NOT NULL REFERENCES stocks(id),
            date            date NOT NULL,
            sma_50          numeric(18, 4),
            sma_200         numeric(18, 4),
            ema_20          numeric(18, 4),
            rsi_14          numeric(9, 4),
            macd            numeric(18, 6),
            macd_signal     numeric(18, 6),
            bollinger_upper numeric(18, 4),
            bollinger_lower numeric(18, 4),
            atr_14          numeric(18, 6),
            ret_3m          numeric(18, 6),
            ret_6m          numeric(18, 6),
            ret_12m         numeric(18, 6),
            vol_30d         numeric(18, 6),
            beta_1y         numeric(18, 6),
            PRIMARY KEY (id, date),
            UNIQUE (stock_id, date)
        ) PARTITION BY RANGE (date);
        """
    )
    op.execute(
        "CREATE INDEX ix_technical_indicators_stock_id_date "
        "ON technical_indicators (stock_id, date DESC);"
    )
    _bootstrap_partitions("technical_indicators")

    # ---- factor_values (normalized per-factor inputs; decomposition) ----
    op.execute(
        """
        CREATE TABLE factor_values (
            id                  bigint GENERATED ALWAYS AS IDENTITY,
            stock_id            uuid NOT NULL REFERENCES stocks(id),
            date                date NOT NULL,
            factor_key          text NOT NULL,           -- 'roe','pe','ret_6m','beta',...
            raw_value           numeric(20, 6),
            zscore              numeric(18, 6),
            percentile_sector   numeric(9, 4),
            percentile_universe numeric(9, 4),
            PRIMARY KEY (id, date),
            UNIQUE (stock_id, date, factor_key)
        ) PARTITION BY RANGE (date);
        """
    )
    op.execute(
        "CREATE INDEX ix_factor_values_stock_id_date "
        "ON factor_values (stock_id, date DESC);"
    )
    _bootstrap_partitions("factor_values")

    # ---- scores (read-hot: current scores/rankings, cached) ----
    op.execute(
        """
        CREATE TABLE scores (
            id                bigint GENERATED ALWAYS AS IDENTITY,
            stock_id          uuid NOT NULL REFERENCES stocks(id),
            date              date NOT NULL,
            fundamental_score numeric(6, 2),
            momentum_score    numeric(6, 2),
            quality_score     numeric(6, 2),
            sentiment_score   numeric(6, 2),
            risk_score        numeric(6, 2),
            composite_score   numeric(6, 2),
            ml_score          numeric(6, 2),            -- secondary ML signal (06/12), nullable
            coverage          numeric(5, 2),            -- % of factors available
            weights_version   text NOT NULL,
            model_version     text NOT NULL,
            created_at        timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (id, date),
            UNIQUE (stock_id, date)
        ) PARTITION BY RANGE (date);
        """
    )
    op.execute("CREATE INDEX ix_scores_date_composite ON scores (date, composite_score DESC);")
    op.execute("CREATE INDEX ix_scores_stock_id_date ON scores (stock_id, date DESC);")
    _bootstrap_partitions("scores")


def downgrade() -> None:
    for tbl in ("scores", "factor_values", "technical_indicators"):
        op.execute(f"DROP TABLE IF EXISTS {tbl} CASCADE;")
