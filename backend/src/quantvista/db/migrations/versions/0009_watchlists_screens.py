"""0009 watchlists & saved screens (tenant-scoped, RLS)

watchlists, watchlist_items, saved_screens.

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-14
"""

from __future__ import annotations

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def _enable_rls(table: str) -> None:
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
        CREATE TABLE watchlists (
            id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id  uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            user_id    uuid NOT NULL REFERENCES users(id),
            name       text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_watchlists_tenant_id ON watchlists (tenant_id);
        """
    )

    op.execute(
        """
        CREATE TABLE watchlist_items (
            id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id    uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            watchlist_id uuid NOT NULL REFERENCES watchlists(id) ON DELETE CASCADE,
            stock_id     uuid NOT NULL REFERENCES stocks(id),
            added_at     timestamptz NOT NULL DEFAULT now(),
            UNIQUE (watchlist_id, stock_id)
        );
        CREATE INDEX ix_watchlist_items_tenant_id ON watchlist_items (tenant_id);
        """
    )

    op.execute(
        """
        CREATE TABLE saved_screens (
            id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id  uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            user_id    uuid NOT NULL REFERENCES users(id),
            name       text NOT NULL,
            criteria   jsonb NOT NULL,                -- validated against an allow-list in the API
            created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_saved_screens_tenant_id ON saved_screens (tenant_id);
        CREATE INDEX gin_saved_screens_criteria ON saved_screens USING gin (criteria);
        """
    )

    for tbl in ("watchlists", "watchlist_items", "saved_screens"):
        _enable_rls(tbl)


def downgrade() -> None:
    for tbl in ("saved_screens", "watchlist_items", "watchlists"):
        op.execute(f"DROP TABLE IF EXISTS {tbl} CASCADE;")
