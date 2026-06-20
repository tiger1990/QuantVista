"""identity data access (QV-006) — thin SQL over a SQLAlchemy session.

No ORM models yet; hand-written SQL keeps parity with the migrations. RLS access rules:
`users`/`refresh_tokens` are global; `tenants`/`memberships`/`subscriptions` are RLS — read
them via a privileged session or a tenant-bound `session_scope` (see services).
"""

from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import Row, text
from sqlalchemy.orm import Session

# --- users (global) ---


def find_user_by_email(
    session: Session, email: str
) -> Row[tuple[UUID, str | None, str | None]] | None:
    return session.execute(
        text("SELECT id, password_hash, name FROM users WHERE email = :email"),
        {"email": email},
    ).first()


def find_user_by_id(session: Session, user_id: UUID) -> Row[tuple[str, str | None]] | None:
    return session.execute(
        text("SELECT email, name FROM users WHERE id = :id"), {"id": user_id}
    ).first()


def email_exists(session: Session, email: str) -> bool:
    return (
        session.execute(text("SELECT 1 FROM users WHERE email = :email"), {"email": email}).first()
        is not None
    )


def insert_user(session: Session, email: str, password_hash: str, name: str | None) -> UUID:
    new_id = session.execute(
        text(
            "INSERT INTO users (email, password_hash, name, status, mfa_enabled, "
            "created_at, updated_at) "
            "VALUES (:email, :ph, :name, 'active', false, now(), now()) RETURNING id"
        ),
        {"email": email, "ph": password_hash, "name": name},
    ).scalar_one()
    return cast(UUID, new_id)


# --- tenants / memberships / subscriptions (RLS; written via privileged session) ---


def insert_tenant(session: Session, name: str) -> UUID:
    new_id = session.execute(
        text(
            "INSERT INTO tenants (name, type, status, created_at, updated_at) "
            "VALUES (:name, 'individual', 'active', now(), now()) RETURNING id"
        ),
        {"name": name},
    ).scalar_one()
    return cast(UUID, new_id)


def insert_membership(session: Session, tenant_id: UUID, user_id: UUID, role: str) -> None:
    session.execute(
        text(
            "INSERT INTO memberships (tenant_id, user_id, role, created_at) "
            "VALUES (:t, :u, :r, now())"
        ),
        {"t": tenant_id, "u": user_id, "r": role},
    )


def insert_free_subscription(session: Session, tenant_id: UUID) -> None:
    session.execute(
        text(
            "INSERT INTO subscriptions (tenant_id, plan_id, status, created_at, updated_at) "
            "SELECT :t, p.id, 'active', now(), now() FROM plans p WHERE p.code = 'free'"
        ),
        {"t": tenant_id},
    )


def primary_membership(session: Session, user_id: UUID) -> Row[tuple[UUID, str]] | None:
    """The user's active tenant + role (earliest membership). Read with a privileged session."""
    return session.execute(
        text(
            "SELECT tenant_id, role FROM memberships WHERE user_id = :u "
            "ORDER BY created_at ASC LIMIT 1"
        ),
        {"u": user_id},
    ).first()


def tenant_name(session: Session, tenant_id: UUID) -> str | None:
    return session.execute(
        text("SELECT name FROM tenants WHERE id = :t"), {"t": tenant_id}
    ).scalar_one_or_none()


def entitlements_for_tenant(session: Session, tenant_id: UUID) -> dict[str, object]:
    rows = session.execute(
        text(
            "SELECT e.key, e.limit_int, e.flag_bool "
            "FROM subscriptions s JOIN entitlements e ON e.plan_id = s.plan_id "
            "WHERE s.tenant_id = :t"
        ),
        {"t": tenant_id},
    ).all()
    return {key: (limit if limit is not None else flag) for key, limit, flag in rows}


def plan_entitlements(
    session: Session, tenant_id: UUID
) -> list[Row[tuple[str, int | None, bool | None]]]:
    """Structured entitlements (key, limit_int, flag_bool) for a tenant's active plan.

    Distinct columns (unlike the lossy ``entitlements_for_tenant`` used by ``/me``) so the
    EntitlementService can tell an unlimited quota (``limit_int`` NULL) from a false
    capability flag. Reads ``subscriptions`` (RLS) → run inside ``session_scope(tenant_id)``.
    """
    return list(
        session.execute(
            text(
                "SELECT e.key, e.limit_int, e.flag_bool "
                "FROM subscriptions s JOIN entitlements e ON e.plan_id = s.plan_id "
                "WHERE s.tenant_id = :t"
            ),
            {"t": tenant_id},
        ).all()
    )


# --- refresh_tokens (global; app role) ---


def insert_refresh_token(
    session: Session,
    user_id: UUID,
    family_id: UUID,
    token_hash: str,
    expires_at: datetime,
) -> UUID:
    new_id = session.execute(
        text(
            "INSERT INTO refresh_tokens (user_id, family_id, token_hash, expires_at) "
            "VALUES (:u, :f, :h, :exp) RETURNING id"
        ),
        {"u": user_id, "f": family_id, "h": token_hash, "exp": expires_at},
    ).scalar_one()
    return cast(UUID, new_id)


def find_refresh_by_hash(
    session: Session, token_hash: str
) -> Row[tuple[UUID, UUID, UUID, datetime, datetime | None]] | None:
    return session.execute(
        text(
            "SELECT id, user_id, family_id, expires_at, revoked_at "
            "FROM refresh_tokens WHERE token_hash = :h"
        ),
        {"h": token_hash},
    ).first()


def revoke_refresh(session: Session, token_id: UUID, replaced_by: UUID | None = None) -> None:
    session.execute(
        text(
            "UPDATE refresh_tokens SET revoked_at = now(), replaced_by = :rb "
            "WHERE id = :id AND revoked_at IS NULL"
        ),
        {"id": token_id, "rb": replaced_by},
    )


def revoke_family(session: Session, family_id: UUID) -> None:
    session.execute(
        text(
            "UPDATE refresh_tokens SET revoked_at = now() "
            "WHERE family_id = :f AND revoked_at IS NULL"
        ),
        {"f": family_id},
    )
