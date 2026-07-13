"""Unit tests for the optimize DTOs + DTO→Constraints mapping (QV-055) — pure, no DB, no cvxpy.

The wire DTO (``schemas.optimize``) enforces per-field and cross-field bounds at the edge; the
api-layer ``_to_constraints`` maps it to the frozen ``portfolio.Constraints`` domain object.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from quantvista.api.routes_portfolios import _to_constraints
from quantvista.schemas.optimize import OptimizeConstraints


def test_valid_constraints_construct() -> None:
    c = OptimizeConstraints(max_weight=Decimal("0.2"), sector_caps={"IT": Decimal("0.4")})
    assert c.long_only is True
    assert c.sector_caps["IT"] == Decimal("0.4")


@pytest.mark.parametrize("bad", [Decimal("0"), Decimal("1.5")])
def test_max_weight_out_of_range_rejected(bad: Decimal) -> None:
    with pytest.raises(ValidationError):
        OptimizeConstraints(max_weight=bad)


def test_sector_cap_out_of_range_rejected() -> None:
    with pytest.raises(ValidationError):
        OptimizeConstraints(sector_caps={"IT": Decimal("1.5")})


def test_min_weight_above_max_rejected() -> None:
    with pytest.raises(ValidationError):
        OptimizeConstraints(max_weight=Decimal("0.2"), min_weight=Decimal("0.3"))


def test_cardinality_min_above_max_rejected() -> None:
    with pytest.raises(ValidationError):
        OptimizeConstraints(cardinality_min=5, cardinality_max=2)


# --- DTO → Constraints mapping (api layer, cvxpy-free) ---


def test_to_constraints_maps_fields() -> None:
    dto = OptimizeConstraints(
        max_weight=Decimal("0.25"),
        sector_caps={"IT": Decimal("0.3")},
        target_return=Decimal("0.12"),
        long_only=True,
    )
    cons = _to_constraints(dto)
    assert cons.max_weight == Decimal("0.25")
    assert cons.sector_caps["IT"] == Decimal("0.3")
    assert cons.target_return == Decimal("0.12")
    assert cons.long_only is True


def test_to_constraints_defaults_min_weight_to_zero() -> None:
    cons = _to_constraints(OptimizeConstraints())
    assert cons.min_weight == Decimal(0)
    assert cons.max_weight is None
    assert dict(cons.sector_caps) == {}
