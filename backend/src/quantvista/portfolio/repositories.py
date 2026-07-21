"""portfolio — data access (QV-051).

All reads/writes run on the **RLS tenant session** (`session_scope(tenant_id)`), so the
`app_current_tenant()` policy scopes them automatically — no manual `tenant_id` filtering (mirrors
`alerts.repositories` / `analytics.saved_screens`). The schema (`portfolios`, `portfolio_positions`)
is forward-declared in migration `0008` — this layer adds no DDL. Money columns are `NUMERIC` →
returned as `Decimal`, never `float`.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


def _portfolio_row(r: Any) -> dict[str, object]:
    return {
        "id": str(r["id"]),
        "name": r["name"],
        "benchmark": r["benchmark"],
        "base_currency": r["base_currency"],
        "created_at": r["created_at"].isoformat(),
        "updated_at": r["updated_at"].isoformat(),
    }


def _position_row(r: Any) -> dict[str, object]:
    return {
        "id": str(r["id"]),
        "portfolio_id": str(r["portfolio_id"]),
        "stock_id": str(r["stock_id"]),
        "symbol": r["symbol"],  # joined from stocks so the UI shows a name, not a raw id
        "weight": r["weight"],  # Decimal | None (numeric)
        "target_weight": r["target_weight"],
        "shares": r["shares"],
        "avg_cost": r["avg_cost"],
    }


_PORTFOLIO_COLS = "id, name, benchmark, base_currency, created_at, updated_at"
_POSITION_COLS = "id, portfolio_id, stock_id, weight, target_weight, shares, avg_cost"


def create_portfolio(
    session: Session,
    *,
    tenant_id: UUID,
    user_id: UUID,
    name: str,
    benchmark: str = "NIFTY200_TRI",
    base_currency: str = "INR",
) -> dict[str, object]:
    """Insert a portfolio for the current tenant (RLS-scoped). `tenant_id` is set so the RLS
    `WITH CHECK` passes."""
    row = (
        session.execute(
            text(
                "INSERT INTO portfolios (tenant_id, user_id, name, benchmark, base_currency) "
                "VALUES (:t, :u, :n, :b, :c) "
                f"RETURNING {_PORTFOLIO_COLS}"
            ),
            {"t": tenant_id, "u": user_id, "n": name, "b": benchmark, "c": base_currency},
        )
        .mappings()
        .one()
    )
    return _portfolio_row(row)


def list_portfolios(session: Session) -> list[dict[str, object]]:
    """The current tenant's portfolios, newest first (RLS-scoped)."""
    rows = (
        session.execute(text(f"SELECT {_PORTFOLIO_COLS} FROM portfolios ORDER BY created_at DESC"))
        .mappings()
        .all()
    )
    return [_portfolio_row(r) for r in rows]


def get_portfolio(session: Session, portfolio_id: UUID) -> dict[str, object] | None:
    """One portfolio by id (RLS-scoped); `None` if it doesn't belong to the tenant."""
    row = (
        session.execute(
            text(f"SELECT {_PORTFOLIO_COLS} FROM portfolios WHERE id = :id"),
            {"id": portfolio_id},
        )
        .mappings()
        .first()
    )
    return _portfolio_row(row) if row is not None else None


def delete_portfolio(session: Session, portfolio_id: UUID) -> bool:
    """Delete a portfolio by id (RLS-scoped); `False` if not the tenant's. Positions cascade."""
    row = session.execute(
        text("DELETE FROM portfolios WHERE id = :id RETURNING id"), {"id": portfolio_id}
    ).first()
    return row is not None


def count_portfolios(session: Session) -> int:
    """Portfolio count for the current tenant (RLS-scoped) — the entitlement-limit denominator."""
    count: int = session.execute(text("SELECT count(*) FROM portfolios")).scalar_one()
    return count


def upsert_position(
    session: Session,
    *,
    tenant_id: UUID,
    portfolio_id: UUID,
    stock_id: UUID,
    weight: object | None = None,
    target_weight: object | None = None,
    shares: object | None = None,
    avg_cost: object | None = None,
) -> dict[str, object]:
    """Insert or update a position, keyed by the `(portfolio_id, stock_id)` unique (RLS-scoped)."""
    row = (
        session.execute(
            text(
                "WITH up AS ("
                "INSERT INTO portfolio_positions "
                "(tenant_id, portfolio_id, stock_id, weight, target_weight, shares, avg_cost) "
                "VALUES (:t, :p, :s, :w, :tw, :sh, :ac) "
                "ON CONFLICT (portfolio_id, stock_id) DO UPDATE SET "
                "weight = EXCLUDED.weight, target_weight = EXCLUDED.target_weight, "
                "shares = EXCLUDED.shares, avg_cost = EXCLUDED.avg_cost "
                f"RETURNING {_POSITION_COLS}"
                ") SELECT up.id, up.portfolio_id, up.stock_id, up.weight, up.target_weight, "
                "up.shares, up.avg_cost, s.symbol "
                "FROM up JOIN stocks s ON s.id = up.stock_id"
            ),
            {
                "t": tenant_id,
                "p": portfolio_id,
                "s": stock_id,
                "w": weight,
                "tw": target_weight,
                "sh": shares,
                "ac": avg_cost,
            },
        )
        .mappings()
        .one()
    )
    return _position_row(row)


def list_positions(session: Session, portfolio_id: UUID) -> list[dict[str, object]]:
    """A portfolio's positions, insertion order (RLS-scoped)."""
    rows = (
        session.execute(
            text(
                "SELECT pp.id, pp.portfolio_id, pp.stock_id, pp.weight, pp.target_weight, "
                "pp.shares, pp.avg_cost, s.symbol "
                "FROM portfolio_positions pp JOIN stocks s ON s.id = pp.stock_id "
                "WHERE pp.portfolio_id = :p ORDER BY pp.created_at"
            ),
            {"p": portfolio_id},
        )
        .mappings()
        .all()
    )
    return [_position_row(r) for r in rows]


def delete_position(session: Session, portfolio_id: UUID, stock_id: UUID) -> bool:
    """Remove one position by `(portfolio_id, stock_id)` (RLS-scoped); `False` if absent."""
    row = session.execute(
        text(
            "DELETE FROM portfolio_positions WHERE portfolio_id = :p AND stock_id = :s RETURNING id"
        ),
        {"p": portfolio_id, "s": stock_id},
    ).first()
    return row is not None
