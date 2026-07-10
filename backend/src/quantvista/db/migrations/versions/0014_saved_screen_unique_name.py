"""0014 saved_screens: unique name per tenant

`saved_screens` was created in 0009 (watchlists & saved screens). This adds a per-tenant
UNIQUE(tenant_id, name) so a saved screen is unambiguous by name (and duplicate saves surface as
409 conflict in the API, QV-039).

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
        "ALTER TABLE saved_screens "
        "ADD CONSTRAINT uq_saved_screens_tenant_name UNIQUE (tenant_id, name);"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE saved_screens DROP CONSTRAINT IF EXISTS uq_saved_screens_tenant_name;")
