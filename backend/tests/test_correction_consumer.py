"""Correction consumer (QV-027) — FundamentalsRevised → recompute_on_correction per affected pair.

The self-heal enqueue edge: a published FundamentalsRevised fans out to one recompute task per
revised filing. `.delay` is patched (no broker); we assert the affected `(stock, period, type)`.
"""

from __future__ import annotations

import pytest

from quantvista.core.events import InProcessEventBus
from quantvista.jobs.consumers import register_pipeline_consumers
from quantvista.jobs.corrections import recompute_on_correction


def test_fundamentals_revised_enqueues_recompute_per_pair(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(recompute_on_correction, "delay", lambda *a: calls.append(a))
    bus = InProcessEventBus()
    register_pipeline_consumers(bus)
    bus.publish(
        "FundamentalsRevised",
        {
            "market": "NSE",
            "knowledge_time": "2026-02-10T00:00:00+00:00",
            "revisions": [
                {"stock_id": "s1", "period_end": "2025-12-31", "statement_type": "quarterly"},
                {"stock_id": "s2", "period_end": "2025-09-30", "statement_type": "annual"},
            ],
        },
    )
    assert calls == [
        ("s1", "2025-12-31", "quarterly"),
        ("s2", "2025-09-30", "annual"),
    ]


def test_no_revisions_enqueues_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(recompute_on_correction, "delay", lambda *a: calls.append(a))
    bus = InProcessEventBus()
    register_pipeline_consumers(bus)
    bus.publish(
        "FundamentalsRevised",
        {"market": "NSE", "knowledge_time": "2026-02-10T00:00:00+00:00", "revisions": []},
    )
    assert calls == []
