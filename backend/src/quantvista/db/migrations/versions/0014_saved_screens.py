"""0014 saved_screens (tenant-scoped, RLS)

User-saved screener definitions (name + validated criteria) for reuse (04 §3.4). Tenant-isolated
via the standard app_current_tenant() policy; entitlement-limited in the API.

Revision ID: 0014
Revises: 0013
Create Date: 2026-07-08
"""

from __future__ import annotations

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE saved_screens (
            id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id   uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            user_id     uuid NOT NULL REFERENCES users(id),
            name        text NOT NULL,
            criteria    jsonb NOT NULL,          -- { market, filters:[{field,op,value}], sort }
            created_at  timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, name)
        );
        CREATE INDEX ix_saved_screens_tenant_id ON saved_screens (tenant_id);
        """
    )

    op.execute("ALTER TABLE saved_screens ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE saved_screens FORCE ROW LEVEL SECURITY;")
    op.execute(
        "CREATE POLICY saved_screens_isolation ON saved_screens "
        "USING (tenant_id = app_current_tenant()) "
        "WITH CHECK (tenant_id = app_current_tenant());"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS saved_screens CASCADE;")
