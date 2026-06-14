"""0004 daily_prices (monthly range partitions, global)

Partitioned by RANGE (date). PK must include the partition key, so PK = (id, date).
Initial partitions cover the current and next month; a maintenance job (or pg_partman)
adds future months via create_month_partition().

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-14
"""

from __future__ import annotations

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE daily_prices (
            id          bigint GENERATED ALWAYS AS IDENTITY,
            stock_id    uuid NOT NULL REFERENCES stocks(id),
            date        date NOT NULL,
            open        numeric(18, 4),
            high        numeric(18, 4),
            low         numeric(18, 4),
            close       numeric(18, 4),
            adj_close   numeric(18, 4),     -- corporate-action adjusted (computed in 0017/job)
            volume      bigint,
            source      text,
            ingested_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (id, date),
            UNIQUE (stock_id, date)         -- unique must include partition key (date) -> ok
        ) PARTITION BY RANGE (date);
        """
    )
    # Indexes propagate to partitions.
    op.execute("CREATE INDEX ix_daily_prices_stock_id_date ON daily_prices (stock_id, date DESC);")
    op.execute("CREATE INDEX brin_daily_prices_date ON daily_prices USING brin (date);")

    # Safety-net default partition + current and next month.
    op.execute(
        "CREATE TABLE daily_prices_default PARTITION OF daily_prices DEFAULT;"
    )
    op.execute("SELECT create_month_partition('daily_prices', date_trunc('month', now())::date);")
    op.execute(
        "SELECT create_month_partition('daily_prices', "
        "date_trunc('month', now() + interval '1 month')::date);"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS daily_prices CASCADE;")
