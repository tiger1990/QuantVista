"""0007 news + sentiment (global)

Store derived sentiment and link to the original article (raw_ref points to object storage);
avoid re-hosting full copyrighted text (03 §1 rule 4).

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-14
"""

from __future__ import annotations

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE news (
            id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            stock_id     uuid REFERENCES stocks(id),       -- NULL = unmatched
            headline     text NOT NULL,
            summary      text,
            source       text,
            source_url   text,
            published_at timestamptz NOT NULL,
            language     text DEFAULT 'en',
            raw_ref      text,                             -- object-store key (not full text inline)
            ingested_at  timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_news_stock_id_published_at ON news (stock_id, published_at DESC);
        CREATE INDEX ix_news_published_at ON news (published_at DESC);
        -- dedup on source URL when present
        CREATE UNIQUE INDEX uq_news_source_url ON news (source_url) WHERE source_url IS NOT NULL;
        """
    )

    op.execute(
        """
        CREATE TABLE sentiment (
            id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            news_id       uuid NOT NULL REFERENCES news(id) ON DELETE CASCADE,
            label         text NOT NULL CHECK (label IN ('positive','negative','neutral')),
            score         numeric(9, 6),
            confidence    numeric(9, 6),
            impact_score  numeric(9, 4),
            model_version text NOT NULL,
            created_at    timestamptz NOT NULL DEFAULT now(),
            UNIQUE (news_id, model_version)
        );
        CREATE INDEX ix_sentiment_news_id ON sentiment (news_id);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS sentiment CASCADE;")
    op.execute("DROP TABLE IF EXISTS news CASCADE;")
