"""Reference seed: idempotency + content (QV-005).

Applies `seed_reference.sql` via `psql -f` (exactly as compose/CI load it), twice, and
asserts the data is present and that re-running is a no-op. Runs as the admin role —
reference data is global and admin-written.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from sqlalchemy import Engine, text

from quantvista.core.config import get_settings

pytestmark = pytest.mark.integration

SEED = Path(__file__).resolve().parents[2] / "src/quantvista/db/seeds/seed_reference.sql"


def _libpq_url() -> str:
    # psql needs a libpq URL, not the SQLAlchemy driver form.
    return get_settings().admin_database_url.replace("postgresql+psycopg://", "postgresql://")


def _run_seed() -> None:
    result = subprocess.run(
        ["psql", _libpq_url(), "-v", "ON_ERROR_STOP=1", "-q", "-f", str(SEED)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"seed failed:\n{result.stderr}"


def _counts(engine: Engine) -> dict[str, int]:
    with engine.connect() as conn:

        def q(sql: str) -> int:
            return int(conn.execute(text(sql)).scalar_one())

        return {
            "markets": q("SELECT count(*) FROM markets"),
            "plans": q("SELECT count(*) FROM plans"),
            "entitlements": q("SELECT count(*) FROM entitlements"),
            "stocks": q("SELECT count(*) FROM stocks"),
            "nifty200": q(
                "SELECT count(*) FROM index_constituents "
                "WHERE index_code = 'NIFTY200' AND effective_to IS NULL"
            ),
        }


def test_seed_is_idempotent_and_populated(admin_engine: Engine) -> None:
    # Act — apply twice
    _run_seed()
    first = _counts(admin_engine)
    _run_seed()
    second = _counts(admin_engine)

    # Idempotent: re-running changes nothing
    assert first == second
    # Populated
    assert first["markets"] >= 1
    assert first["plans"] >= 3
    assert first["entitlements"] >= 1
    assert first["stocks"] >= 10
    assert first["nifty200"] >= 10


def test_seed_plans_and_pit_membership(admin_engine: Engine) -> None:
    _run_seed()
    with admin_engine.connect() as conn:
        plans = {row[0] for row in conn.execute(text("SELECT code FROM plans"))}
        assert {"free", "pro", "quant"} <= plans

        # NSE market exists.
        nse = conn.execute(text("SELECT count(*) FROM markets WHERE code = 'NSE'")).scalar_one()
        assert nse == 1

        # Every current NIFTY200 member is point-in-time dated (effective_from set).
        undated = conn.execute(
            text(
                "SELECT count(*) FROM index_constituents "
                "WHERE index_code = 'NIFTY200' AND effective_to IS NULL AND effective_from IS NULL"
            )
        ).scalar_one()
        assert undated == 0
