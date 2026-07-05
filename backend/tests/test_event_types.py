"""Round-trip + contract tests for the typed domain events (QV-024)."""

from __future__ import annotations

import json

from quantvista.core.event_types import (
    FactorsComputed,
    FundamentalsUpdated,
    IndicatorsComputed,
    NewsScored,
    PricesIngested,
    PricesValidated,
    ScoresComputed,
)

_EVENTS = [
    PricesIngested(
        market="NSE", start="2026-06-01", end="2026-06-01", stocks_ok=12, rows_upserted=12
    ),
    PricesValidated(
        market="NSE", start="2026-06-01", end="2026-06-01", stocks_validated=12, expected_stocks=12
    ),
    FundamentalsUpdated(
        market="NSE", knowledge_time="2026-06-01T00:00:00+00:00", inserted=1, revised=0, unchanged=2
    ),
    IndicatorsComputed(market="NSE", date="2026-06-01", stocks=12),
    FactorsComputed(
        market="NSE", date="2026-06-01", model_version="score-v1", stock_count=12, factor_count=96
    ),
    ScoresComputed(universe="NIFTY200", date="2026-06-01", model_version="score-v1", count=200),
    NewsScored(news_batch="b-1", count=5),
]


def test_topics_are_the_expected_contract() -> None:
    assert {type(e).TOPIC for e in _EVENTS} == {
        "PricesIngested",
        "PricesValidated",
        "FundamentalsUpdated",
        "IndicatorsComputed",
        "FactorsComputed",
        "ScoresComputed",
        "NewsScored",
    }


def test_payload_round_trips_and_excludes_classvars() -> None:
    for e in _EVENTS:
        payload = e.to_payload()
        assert "TOPIC" not in payload and "VERSION" not in payload  # ClassVars aren't fields
        assert type(e).from_payload(payload) == e  # exact round-trip


def test_payload_is_json_safe() -> None:
    for e in _EVENTS:
        # A stream/Kafka value must serialize + deserialize unchanged.
        assert json.loads(json.dumps(e.to_payload())) == e.to_payload()
