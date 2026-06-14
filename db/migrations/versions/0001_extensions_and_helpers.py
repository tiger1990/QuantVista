"""0001 extensions and helper functions

Sets up pgcrypto (gen_random_uuid), the tenant-context reader used by all RLS policies,
an updated_at trigger function, and a monthly-partition helper.

Revision ID: 0001
Revises:
Create Date: 2026-06-14
"""

from __future__ import annotations

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # gen_random_uuid() for UUID PKs; btree_gin for mixed btree+GIN indexes on JSONB filters.
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gin;")

    # Tenant context reader. Every request runs `SET LOCAL app.tenant_id = '<uuid>'`.
    # The `true` second arg makes a missing setting return NULL (no rows) instead of erroring.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app_current_tenant() RETURNS uuid
        LANGUAGE sql STABLE AS $$
            SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid
        $$;
        """
    )

    # Generic updated_at maintenance trigger.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$;
        """
    )

    # Helper to create a monthly range partition: idempotent, names like daily_prices_2026_06.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION create_month_partition(parent text, month_start date)
        RETURNS void LANGUAGE plpgsql AS $$
        DECLARE
            part_name text := format('%s_%s', parent, to_char(month_start, 'YYYY_MM'));
            month_end  date := (month_start + interval '1 month')::date;
        BEGIN
            EXECUTE format(
                'CREATE TABLE IF NOT EXISTS %I PARTITION OF %I FOR VALUES FROM (%L) TO (%L)',
                part_name, parent, month_start, month_end
            );
        END;
        $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS create_month_partition(text, date);")
    op.execute("DROP FUNCTION IF EXISTS set_updated_at();")
    op.execute("DROP FUNCTION IF EXISTS app_current_tenant();")
    # Extensions left in place; dropping them can affect other objects.
