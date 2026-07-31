"""The published methodology page must not drift from the engine (QV-070).

`/methodology` states the weights, versions and cost assumptions as fact. Those values are mirrored
into `frontend/src/lib/methodology.ts` (and the non-advice line into `.../disclaimer.ts`) because
TypeScript cannot import Python. A published page that quietly disagrees with the code is worse
than no page — so these tests read the frontend constants and compare them against the backend,
which is the source of truth. Change a weight in Python and this suite tells you the page lies.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from quantvista.analytics.backtest import SLIPPAGE_BPS, WEIGHTS_VERSION
from quantvista.analytics.normalizer import _WINSOR_HI, _WINSOR_LO
from quantvista.analytics.scoring import DEFAULT_WEIGHTS, MODEL_VERSION
from quantvista.api.routes_stocks import DISCLAIMER
from quantvista.schemas.backtest import BacktestSpec

_FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib"
_METHODOLOGY_TS = _FRONTEND / "methodology.ts"
_DISCLAIMER_TS = _FRONTEND / "disclaimer.ts"


def _source(path: Path) -> str:
    if not path.exists():  # pragma: no cover - guards a rename, not a normal state
        pytest.fail(f"{path} is missing: the methodology page's constants have moved or been lost")
    return path.read_text(encoding="utf-8")


def _const(source: str, name: str) -> str:
    """The literal assigned to `export const <name> = ...` (string or number)."""
    match = re.search(rf'export const {name}\s*=\s*"?([^";\n]+)"?;', source)
    assert match, f"{name} not found in the frontend methodology constants"
    return match.group(1).strip()


def test_disclaimer_has_one_source() -> None:
    """The compliance line ships in every API response; the UI must say exactly the same thing."""
    assert _const(_source(_DISCLAIMER_TS), "DISCLAIMER") == DISCLAIMER


def test_model_and_weight_versions_match() -> None:
    src = _source(_METHODOLOGY_TS)
    assert _const(src, "MODEL_VERSION") == MODEL_VERSION
    assert _const(src, "SCORING_WEIGHTS_VERSION") == DEFAULT_WEIGHTS.version
    assert _const(src, "BACKTEST_WEIGHTS_VERSION") == WEIGHTS_VERSION


def test_published_category_weights_match_the_engine() -> None:
    """The weights table is the page's most load-bearing claim."""
    src = _source(_METHODOLOGY_TS)
    published = {
        category.lower(): float(weight)
        for category, weight in re.findall(
            r'\{\s*category:\s*"([^"]+)",\s*weight:\s*([0-9.]+)\s*\}', src
        )
    }
    actual = {
        "fundamental": DEFAULT_WEIGHTS.fundamental,
        "momentum": DEFAULT_WEIGHTS.momentum,
        "quality": DEFAULT_WEIGHTS.quality,
        "sentiment": DEFAULT_WEIGHTS.sentiment,
        "risk": DEFAULT_WEIGHTS.risk,
    }
    assert published == pytest.approx(actual)
    assert sum(published.values()) == pytest.approx(1.0)


def test_cost_assumptions_match() -> None:
    src = _source(_METHODOLOGY_TS)
    assert int(_const(src, "SLIPPAGE_BPS")) == SLIPPAGE_BPS
    # the accepted commission ceiling, straight off the validated spec field
    ceiling = BacktestSpec.model_fields["costs_bps"].metadata
    assert int(_const(src, "COSTS_BPS_MAX")) == next(
        m.le for m in ceiling if getattr(m, "le", None) is not None
    )


def test_winsor_band_matches() -> None:
    src = _source(_METHODOLOGY_TS)
    assert int(_const(src, "WINSOR_LO_PCT")) == round(_WINSOR_LO * 100)
    assert int(_const(src, "WINSOR_HI_PCT")) == round(_WINSOR_HI * 100)
