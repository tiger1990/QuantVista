"""Pipeline event consumers (QV-025) — publishing on the shared bus enqueues the right task.

Both DAG edges: PricesIngested → validate_prices.delay, PricesValidated → compute_indicators.delay.
Celery `.delay` is patched (no broker); we assert (market, date) come from the envelope payload.
"""

from __future__ import annotations

import pytest

from quantvista.core.events import InProcessEventBus
from quantvista.jobs.compute import compute_indicators
from quantvista.jobs.consumers import register_pipeline_consumers
from quantvista.jobs.quality import validate_prices
from quantvista.jobs.scoring import compute_factors, compute_scores


def test_prices_ingested_enqueues_validate_prices(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(validate_prices, "delay", lambda *a: calls.append(a))
    bus = InProcessEventBus()
    register_pipeline_consumers(bus)
    bus.publish("PricesIngested", {"market": "NSE", "start": "2026-06-01", "end": "2026-06-01"})
    assert calls == [("NSE", "2026-06-01")]


def test_prices_validated_enqueues_compute_indicators(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(compute_indicators, "delay", lambda *a: calls.append(a))
    bus = InProcessEventBus()
    register_pipeline_consumers(bus)
    bus.publish("PricesValidated", {"market": "NSE", "start": "2026-06-02", "end": "2026-06-02"})
    assert calls == [("NSE", "2026-06-02")]


def test_indicators_computed_enqueues_compute_factors(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(compute_factors, "delay", lambda *a: calls.append(a))
    bus = InProcessEventBus()
    register_pipeline_consumers(bus)
    bus.publish("IndicatorsComputed", {"market": "NSE", "date": "2026-06-03", "stocks": 5})
    assert calls == [("NSE", "2026-06-03")]


def test_factors_computed_enqueues_compute_scores(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(compute_scores, "delay", lambda *a: calls.append(a))
    bus = InProcessEventBus()
    register_pipeline_consumers(bus)
    bus.publish("FactorsComputed", {"market": "NSE", "date": "2026-06-03", "factors": 40})
    assert calls == [("NSE", "2026-06-03")]


def test_register_subscribes_both_edges(monkeypatch: pytest.MonkeyPatch) -> None:
    v: list[tuple[object, ...]] = []
    c: list[tuple[object, ...]] = []
    monkeypatch.setattr(validate_prices, "delay", lambda *a: v.append(a))
    monkeypatch.setattr(compute_indicators, "delay", lambda *a: c.append(a))
    bus = InProcessEventBus()
    register_pipeline_consumers(bus)
    bus.publish("PricesIngested", {"market": "NSE", "start": "d", "end": "d1"})
    bus.publish("PricesValidated", {"market": "NSE", "start": "d", "end": "d2"})
    assert v == [("NSE", "d1")] and c == [("NSE", "d2")]
