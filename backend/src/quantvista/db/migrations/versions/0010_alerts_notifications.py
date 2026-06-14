"""0010 alerts & notifications (tenant-scoped, RLS)

alert_rules, alert_events, notifications.

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-14
"""

from __future__ import annotations

from alembic import op

revision = "0010"
down_revision = "0009"
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
        CREATE TABLE alert_rules (
            id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id  uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            user_id    uuid NOT NULL REFERENCES users(id),
            scope      text NOT NULL CHECK (scope IN ('stock','portfolio')),
            target_id  uuid NOT NULL,                 -- stock_id or portfolio_id (by scope)
            condition  jsonb NOT NULL,                -- {metric, op, value}; allow-list validated
            channel    text NOT NULL DEFAULT 'in_app'
                       CHECK (channel IN ('in_app','email','webhook')),
            is_active  boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_alert_rules_tenant_id ON alert_rules (tenant_id);
        CREATE INDEX ix_alert_rules_active ON alert_rules (is_active) WHERE is_active;
        """
    )

    op.execute(
        """
        CREATE TABLE alert_events (
            id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id     uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            alert_rule_id uuid NOT NULL REFERENCES alert_rules(id) ON DELETE CASCADE,
            fired_at      timestamptz NOT NULL DEFAULT now(),
            dedup_key     text NOT NULL,              -- prevents duplicate fires per cycle
            payload       jsonb NOT NULL DEFAULT '{}'::jsonb,
            delivered_at  timestamptz,
            status        text NOT NULL DEFAULT 'pending'
                          CHECK (status IN ('pending','delivered','failed')),
            UNIQUE (alert_rule_id, dedup_key)
        );
        CREATE INDEX ix_alert_events_tenant_id ON alert_events (tenant_id);
        """
    )

    op.execute(
        """
        CREATE TABLE notifications (
            id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id  uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            user_id    uuid NOT NULL REFERENCES users(id),
            type       text NOT NULL,
            payload    jsonb NOT NULL DEFAULT '{}'::jsonb,
            read_at    timestamptz,
            created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_notifications_tenant_user
            ON notifications (tenant_id, user_id, created_at DESC);
        """
    )

    op.execute(
        "CREATE TRIGGER trg_alert_rules_updated_at BEFORE UPDATE ON alert_rules "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
    )

    for tbl in ("alert_rules", "alert_events", "notifications"):
        _enable_rls(tbl)


def downgrade() -> None:
    for tbl in ("notifications", "alert_events", "alert_rules"):
        op.execute(f"DROP TABLE IF EXISTS {tbl} CASCADE;")
