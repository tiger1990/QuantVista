"""0013 auth: refresh_tokens (global identity, rotation + reuse detection)

Stores hashed refresh tokens for rotation and theft detection (07 §2). Global identity
table: a refresh token belongs to a user (who may span tenants) and is read during auth
*before* tenant context exists — so NO tenant_id and NO RLS. Tokens are never stored raw
(only a SHA-256 hash). `family_id` links a rotation lineage so reuse of a rotated token
revokes the whole family.

Revision ID: 0013
Revises: 0012
Create Date: 2026-06-20
"""

from __future__ import annotations

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE refresh_tokens (
            id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            family_id   uuid NOT NULL,                 -- rotation lineage (reuse -> revoke family)
            token_hash  text NOT NULL,                 -- SHA-256 of the opaque token; never raw
            issued_at   timestamptz NOT NULL DEFAULT now(),
            expires_at  timestamptz NOT NULL,
            revoked_at  timestamptz,                   -- set on rotation / logout / reuse-revoke
            replaced_by uuid REFERENCES refresh_tokens(id),
            user_agent  text,
            created_at  timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_refresh_tokens_token_hash UNIQUE (token_hash)
        );
        CREATE INDEX ix_refresh_tokens_user_id ON refresh_tokens (user_id);
        CREATE INDEX ix_refresh_tokens_family_id ON refresh_tokens (family_id);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS refresh_tokens CASCADE;")
