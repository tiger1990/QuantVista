"""0016 alerts (tenant-scoped, RLS)

alert_rules + alert_events (QV-047). Rules are user-configured, condition validated against an
allow-list in the API (03 §4.3). Events are written by evaluate_alerts (QV-048) and delivered by
QV-049 — the table is created here, empty. Both tenant-isolated via app_current_tenant().

Revision ID: 0016
Revises: 0015
Create Date: 2026-07-12
"""

from __future__ import annotations

from alembic import op

revision = "0016"
down_revision = "0015"
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
            target_id  uuid NOT NULL,                 -- a stock_id or portfolio_id (by scope)
            condition  jsonb NOT NULL,                -- {metric, op, value}; allow-list-validated in the API
            channel    text NOT NULL CHECK (channel IN ('email','in_app')),
            is_active  boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_alert_rules_tenant_id ON alert_rules (tenant_id);
        -- QV-048 evaluates active rules per tenant.
        CREATE INDEX ix_alert_rules_active ON alert_rules (tenant_id) WHERE is_active;
        """
    )

    op.execute(
        """
        CREATE TABLE alert_events (
            id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id     uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            alert_rule_id uuid NOT NULL REFERENCES alert_rules(id) ON DELETE CASCADE,
            fired_at      timestamptz NOT NULL DEFAULT now(),
            payload       jsonb NOT NULL,
            delivered_at  timestamptz,
            status        text NOT NULL DEFAULT 'pending'
                          CHECK (status IN ('pending','delivered','failed'))
        );
        CREATE INDEX ix_alert_events_tenant_id ON alert_events (tenant_id);
        CREATE INDEX ix_alert_events_rule ON alert_events (alert_rule_id, fired_at DESC);
        """
    )

    for tbl in ("alert_rules", "alert_events"):
        _enable_rls(tbl)


def downgrade() -> None:
    for tbl in ("alert_events", "alert_rules"):
        op.execute(f"DROP TABLE IF EXISTS {tbl} CASCADE;")
