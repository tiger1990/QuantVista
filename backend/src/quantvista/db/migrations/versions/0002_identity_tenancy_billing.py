"""0002 identity, tenancy, billing

tenants, users, memberships (tenant-scoped) + plans, entitlements (global reference)
+ subscriptions (tenant-scoped). RLS applied to tenant-scoped tables.

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-14
"""

from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- tenants (tenant-scoped: a tenant is its own boundary; policy keys on id) ----
    op.execute(
        """
        CREATE TABLE tenants (
            id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            name        text NOT NULL,
            type        text NOT NULL DEFAULT 'individual'
                        CHECK (type IN ('individual', 'org')),
            status      text NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'suspended', 'closed')),
            created_at  timestamptz NOT NULL DEFAULT now(),
            updated_at  timestamptz NOT NULL DEFAULT now()
        );
        """
    )

    # ---- users (GLOBAL identity: a user may belong to multiple tenants via memberships;
    #      access governed by the app + memberships, not row-level tenant scoping) ----
    op.execute(
        """
        CREATE TABLE users (
            id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            email         text NOT NULL,
            password_hash text,
            name          text,
            status        text NOT NULL DEFAULT 'active'
                          CHECK (status IN ('active', 'disabled')),
            mfa_enabled   boolean NOT NULL DEFAULT false,
            last_login_at timestamptz,
            created_at    timestamptz NOT NULL DEFAULT now(),
            updated_at    timestamptz NOT NULL DEFAULT now()
        );
        """
    )
    # Case-insensitive uniqueness on email.
    op.execute("CREATE UNIQUE INDEX uq_users_email ON users (lower(email));")

    # ---- memberships (tenant-scoped) ----
    op.execute(
        """
        CREATE TABLE memberships (
            id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id  uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            user_id    uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            role       text NOT NULL DEFAULT 'member'
                       CHECK (role IN ('owner', 'admin', 'member')),
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, user_id)
        );
        CREATE INDEX ix_memberships_user_id ON memberships (user_id);
        """
    )

    # ---- plans (GLOBAL reference) ----
    op.execute(
        """
        CREATE TABLE plans (
            id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            code             text NOT NULL UNIQUE
                             CHECK (code IN ('free', 'pro', 'quant')),
            name             text NOT NULL,
            price_inr        numeric(12, 2) NOT NULL DEFAULT 0,
            billing_interval text NOT NULL DEFAULT 'month'
                             CHECK (billing_interval IN ('month', 'year')),
            is_active        boolean NOT NULL DEFAULT true,
            created_at       timestamptz NOT NULL DEFAULT now()
        );
        """
    )

    # ---- entitlements (GLOBAL reference: limits/flags per plan) ----
    op.execute(
        """
        CREATE TABLE entitlements (
            id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            plan_id   uuid NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
            key       text NOT NULL,           -- e.g. max_portfolios, backtest, api_access
            limit_int integer,                 -- NULL = unlimited or not-a-limit
            flag_bool boolean,                 -- for boolean capabilities
            UNIQUE (plan_id, key)
        );
        """
    )

    # ---- subscriptions (tenant-scoped) ----
    op.execute(
        """
        CREATE TABLE subscriptions (
            id                     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id              uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            plan_id                uuid NOT NULL REFERENCES plans(id),
            stripe_subscription_id text UNIQUE,
            status                 text NOT NULL DEFAULT 'active'
                                   CHECK (status IN ('trialing','active','past_due','canceled')),
            current_period_end     timestamptz,
            created_at             timestamptz NOT NULL DEFAULT now(),
            updated_at             timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id)     -- one active subscription record per tenant
        );
        """
    )

    # updated_at triggers
    for tbl in ("tenants", "users", "subscriptions"):
        op.execute(
            f"CREATE TRIGGER trg_{tbl}_updated_at BEFORE UPDATE ON {tbl} "
            f"FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
        )

    # ---- RLS on tenant-scoped tables ----
    # tenants: a session may only see its own tenant row.
    op.execute("ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE tenants FORCE ROW LEVEL SECURITY;")
    op.execute(
        "CREATE POLICY tenants_isolation ON tenants "
        "USING (id = app_current_tenant()) WITH CHECK (id = app_current_tenant());"
    )
    for tbl in ("memberships", "subscriptions"):
        op.execute(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {tbl} FORCE ROW LEVEL SECURITY;")
        op.execute(
            f"CREATE POLICY {tbl}_isolation ON {tbl} "
            f"USING (tenant_id = app_current_tenant()) "
            f"WITH CHECK (tenant_id = app_current_tenant());"
        )


def downgrade() -> None:
    for tbl in ("subscriptions", "entitlements", "plans", "memberships", "users", "tenants"):
        op.execute(f"DROP TABLE IF EXISTS {tbl} CASCADE;")
