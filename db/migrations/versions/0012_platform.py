"""0012 platform: audit_log + jobs_runs (global, append-mostly)

audit_log: security/money-relevant actions (07 §6). jobs_runs: pipeline run records (06 §1).
Both are global/operational; audit_log carries an optional tenant_id for filtering but is not
RLS-restricted (it is read by operators/compliance, not tenants).

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-14
"""

from __future__ import annotations

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE audit_log (
            id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            actor_user_id uuid REFERENCES users(id),
            tenant_id     uuid REFERENCES tenants(id),
            action        text NOT NULL,             -- 'login','portfolio.create','billing.change'...
            entity        text,
            entity_id     text,
            before        jsonb,
            after         jsonb,
            ip            inet,
            created_at    timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_audit_log_tenant_id_created_at ON audit_log (tenant_id, created_at DESC);
        CREATE INDEX ix_audit_log_action_created_at ON audit_log (action, created_at DESC);
        """
    )
    # Append-only guard: block UPDATE/DELETE on audit_log (immutability, 07 §6).
    op.execute(
        """
        CREATE OR REPLACE FUNCTION audit_log_immutable() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'audit_log is append-only';
        END;
        $$;
        CREATE TRIGGER trg_audit_log_no_update BEFORE UPDATE OR DELETE ON audit_log
            FOR EACH ROW EXECUTE FUNCTION audit_log_immutable();
        """
    )

    op.execute(
        """
        CREATE TABLE jobs_runs (
            id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            job_name    text NOT NULL,
            run_key     text NOT NULL,                -- idempotency key (06 §1)
            status      text NOT NULL DEFAULT 'running'
                        CHECK (status IN ('running','succeeded','failed','skipped')),
            started_at  timestamptz NOT NULL DEFAULT now(),
            finished_at timestamptz,
            rows_in     bigint,
            rows_out    bigint,
            error       text,
            metadata    jsonb NOT NULL DEFAULT '{}'::jsonb,
            UNIQUE (job_name, run_key)
        );
        CREATE INDEX ix_jobs_runs_job_name_started_at ON jobs_runs (job_name, started_at DESC);
        CREATE INDEX ix_jobs_runs_status ON jobs_runs (status);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS jobs_runs CASCADE;")
    op.execute("DROP TABLE IF EXISTS audit_log CASCADE;")
    op.execute("DROP FUNCTION IF EXISTS audit_log_immutable();")
