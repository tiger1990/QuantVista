"""Rankings entitlement-cap logic (QV-033) — pure `effective_limit` (no infra)."""

from __future__ import annotations

from quantvista.api.routes_scores import effective_limit


def test_tier_caps_the_request() -> None:
    assert effective_limit(200, 50) == 50  # Free tier (top-50) caps a larger request
    assert effective_limit(20, 50) == 20  # a smaller request wins


def test_none_tier_is_unlimited() -> None:
    assert effective_limit(200, None) == 200  # paid tier: no cap
    assert effective_limit(50, None) == 50
