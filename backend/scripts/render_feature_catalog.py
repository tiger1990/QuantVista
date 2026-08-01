"""Regenerate `docs/feature-catalog.md` from the feature specs (QV-087).

Usage (from ``backend/`` with the venv active)::

    python scripts/render_feature_catalog.py

`tests/test_feature_catalog.py` fails when the committed file differs from this output.
"""

from __future__ import annotations

from pathlib import Path

from quantvista.analytics.factors import ALL_FACTORS
from quantvista.ml.catalog import render_catalog

OUT = Path(__file__).resolve().parents[2] / "docs" / "feature-catalog.md"


def main() -> None:
    OUT.write_text(render_catalog([f.key for f in ALL_FACTORS]), encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
