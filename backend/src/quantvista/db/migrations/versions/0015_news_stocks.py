"""0015 news_stocks: many-to-many news↔stocks (QV-094)

Replaces the single ``news.stock_id`` FK (QV-042) with a ``news_stocks`` join so an article can be
tagged to every stock it names (multi-stock stories previously matched ≥2 stocks and were left
NULL → shown on no stock's page). ``news.tagged_at`` marks rows the tagger has processed so
market-wide no-match articles aren't re-scanned forever.

Backfill: existing single tags → ``news_stocks``; ``tagged_at`` set only on already-tagged rows, so
the previously-NULL (multi-stock) rows stay ``tagged_at NULL`` and get re-tagged with the new
multi-match logic on the next ``tag_news`` run.

Revision ID: 0015
Revises: 0014
Create Date: 2026-07-11
"""

from __future__ import annotations

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE news_stocks (
            news_id  uuid NOT NULL REFERENCES news(id) ON DELETE CASCADE,
            stock_id uuid NOT NULL REFERENCES stocks(id),
            PRIMARY KEY (news_id, stock_id)
        );
        CREATE INDEX ix_news_stocks_stock_id ON news_stocks (stock_id);

        ALTER TABLE news ADD COLUMN tagged_at timestamptz;

        -- migrate existing single tags into the join
        INSERT INTO news_stocks (news_id, stock_id)
            SELECT id, stock_id FROM news WHERE stock_id IS NOT NULL
            ON CONFLICT DO NOTHING;

        -- mark ONLY the already-tagged rows processed; NULL rows re-tag with multi-match next run
        UPDATE news SET tagged_at = now() WHERE stock_id IS NOT NULL;

        DROP INDEX IF EXISTS ix_news_stock_id_published_at;
        ALTER TABLE news DROP COLUMN stock_id;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE news ADD COLUMN stock_id uuid REFERENCES stocks(id);
        CREATE INDEX ix_news_stock_id_published_at ON news (stock_id, published_at DESC);

        -- restore a single (arbitrary) tag per article from the join
        UPDATE news n SET stock_id = ns.stock_id
        FROM (SELECT DISTINCT ON (news_id) news_id, stock_id
              FROM news_stocks ORDER BY news_id, stock_id) ns
        WHERE ns.news_id = n.id;

        ALTER TABLE news DROP COLUMN tagged_at;
        DROP TABLE IF EXISTS news_stocks;
        """
    )
