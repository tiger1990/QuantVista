"""Database engines and tenant-scoped sessions (Platform/Core infrastructure).

Two engines back the system:

- **app engine** — connects as the NON-superuser role (``Settings.database_url``). All
  tenant-table access goes through it so PostgreSQL Row-Level Security is enforced.
- **privileged engine** — connects as the admin/reference-data role
  (``Settings.admin_database_url``) for writes to GLOBAL/reference tables by background
  jobs. It must never write tenant-scoped tables.

Tenant isolation is bound **per transaction** via ``app.tenant_id`` (read by the
``app_current_tenant()`` SQL function from migration 0001), so RLS policies filter every
query to the current tenant. We use ``set_config(key, value, is_local => true)`` — the
parameterized equivalent of ``SET LOCAL`` — which resets at commit/rollback.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from uuid import UUID

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session

from quantvista.core.config import get_settings

# SQL that binds the tenant for the current transaction (transaction-local).
_SET_TENANT_SQL = text("SELECT set_config('app.tenant_id', :tid, true)")


@lru_cache
def app_engine() -> Engine:
    """Engine for the non-superuser app role (RLS-enforced)."""
    return create_engine(get_settings().database_url, pool_pre_ping=True, future=True)


@lru_cache
def privileged_engine() -> Engine:
    """Engine for the admin/reference-data role (global-table writes only)."""
    return create_engine(get_settings().admin_database_url, pool_pre_ping=True, future=True)


def bind_tenant(session: Session, tenant_id: UUID) -> None:
    """Bind ``app.tenant_id`` for the session's current transaction (RLS scope)."""
    session.execute(_SET_TENANT_SQL, {"tid": str(tenant_id)})


@contextmanager
def session_scope(tenant_id: UUID | None = None) -> Iterator[Session]:
    """A transactional session on the app engine, optionally bound to one tenant.

    Opens a transaction; if ``tenant_id`` is given, binds ``app.tenant_id`` first so RLS
    filters every subsequent query to that tenant; commits on success, rolls back on
    error, always closes. The tenant binding lives exactly one transaction.
    """
    session = Session(app_engine())
    try:
        if tenant_id is not None:
            bind_tenant(session, tenant_id)  # first statement → autobegins the transaction
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def privileged_session_scope() -> Iterator[Session]:
    """A transactional session on the privileged engine for GLOBAL/reference tables.

    No tenant binding. MUST NOT be used to write tenant-scoped tables — those go through
    ``session_scope(tenant_id)`` so RLS applies.
    """
    session = Session(privileged_engine())
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
