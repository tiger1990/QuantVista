"""0005 fundamentals (bitemporal / point-in-time) + shareholding (global)

fundamentals is bitemporal: `period_end` (what period the data describes) plus
`knowledge_from`/`knowledge_to` (when we knew it). A score for date D reads the row where
knowledge_from <= D < knowledge_to. Revisions insert a new version and close the prior one;
nothing is destructively updated (03 §5).

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-14
"""

from __future__ import annotations

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE fundamentals (
            id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            stock_id         uuid NOT NULL REFERENCES stocks(id),
            period_end       date NOT NULL,
            statement_type   text NOT NULL DEFAULT 'quarterly'
                             CHECK (statement_type IN ('quarterly','annual','ttm')),
            -- valuation / profitability / leverage / growth (NUMERIC, never float)
            pe               numeric(18, 6),
            forward_pe       numeric(18, 6),
            pb               numeric(18, 6),
            roe              numeric(18, 6),
            roce             numeric(18, 6),
            roic             numeric(18, 6),
            debt_equity      numeric(18, 6),
            revenue          numeric(20, 2),
            revenue_growth   numeric(18, 6),
            eps              numeric(18, 6),
            eps_growth       numeric(18, 6),
            fcf              numeric(20, 2),
            fcf_growth       numeric(18, 6),
            operating_margin numeric(18, 6),
            net_margin       numeric(18, 6),
            current_ratio    numeric(18, 6),
            quick_ratio      numeric(18, 6),
            ev_ebitda        numeric(18, 6),
            peg              numeric(18, 6),
            price_sales      numeric(18, 6),
            enterprise_value numeric(20, 2),
            -- bitemporal knowledge interval
            reported_at      timestamptz,
            knowledge_from   timestamptz NOT NULL DEFAULT now(),
            knowledge_to     timestamptz,                    -- NULL = currently-known version
            source           text,
            ingested_at      timestamptz NOT NULL DEFAULT now(),
            CHECK (knowledge_to IS NULL OR knowledge_to > knowledge_from)
        );
        -- as_of(date) lookups: latest version known at a date.
        CREATE INDEX ix_fundamentals_stock_period
            ON fundamentals (stock_id, period_end, knowledge_from DESC);
        -- Exactly one open (current) version per (stock, period, statement_type).
        CREATE UNIQUE INDEX uq_fundamentals_open
            ON fundamentals (stock_id, period_end, statement_type)
            WHERE knowledge_to IS NULL;
        """
    )

    op.execute(
        """
        CREATE TABLE shareholding (
            id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            stock_id         uuid NOT NULL REFERENCES stocks(id),
            as_of_date       date NOT NULL,
            promoter_holding numeric(9, 4),
            fii_holding      numeric(9, 4),
            dii_holding      numeric(9, 4),
            public_holding   numeric(9, 4),
            pledged_pct      numeric(9, 4),
            source           text,
            ingested_at      timestamptz NOT NULL DEFAULT now(),
            UNIQUE (stock_id, as_of_date)
        );
        CREATE INDEX ix_shareholding_stock_id_as_of_date
            ON shareholding (stock_id, as_of_date DESC);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS shareholding CASCADE;")
    op.execute("DROP TABLE IF EXISTS fundamentals CASCADE;")
