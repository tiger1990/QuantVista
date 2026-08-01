"""The published feature catalog must match the code (QV-087).

Same reasoning as the QV-011 terminology guide and the QV-070 methodology constants: a document
describing what the system does, maintained by hand, is wrong within two stories. Here it is worse
than cosmetic — the catalog is what a reviewer reads when judging whether a model's inputs are
legitimate, so a stale one is actively misleading.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from quantvista.analytics.factors import ALL_FACTORS
from quantvista.ml.catalog import render_catalog
from quantvista.ml.features import feature_names

_CATALOG = Path(__file__).resolve().parents[2] / "docs" / "feature-catalog.md"
_KEYS = [f.key for f in ALL_FACTORS]


def _catalog_text() -> str:
    if not _CATALOG.exists():  # pragma: no cover - guards a delete/rename
        pytest.fail(f"{_CATALOG} is missing; run scripts/render_feature_catalog.py")
    return _CATALOG.read_text(encoding="utf-8")


def test_catalog_is_current() -> None:
    assert _catalog_text() == render_catalog(_KEYS), (
        "docs/feature-catalog.md is stale — regenerate with "
        "`python scripts/render_feature_catalog.py`"
    )


def test_every_feature_appears_in_the_catalog() -> None:
    """Guards the guard: a rendering bug that dropped rows would still pass an equality check."""
    text = _catalog_text()
    names = feature_names(_KEYS)
    assert len(names) >= 100
    missing = [n for n in names if f"`{n}`" not in text]
    assert missing == [], f"features absent from the catalog: {missing[:5]}"


def test_catalog_states_the_pit_guarantee_and_its_limits() -> None:
    """The catalog's value is the caveats; a feature list alone would not earn the trust."""
    text = _catalog_text().lower()
    for claim in ("point-in-time", "trailing-only", "no forward fill"):
        assert claim in text, f"catalog no longer states: {claim}"
    assert "qv-088" in text, "the catalog must say what is deliberately NOT in scope here"
