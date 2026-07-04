"""Unit tests for the in-process event bus, envelope, and the config-toggle factory (QV-024)."""

from __future__ import annotations

import pytest

from quantvista.core.events import (
    InProcessEventBus,
    build_envelope,
    get_event_bus,
    reset_event_bus,
)


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_event_bus()


def test_envelope_shape_and_unique_ids() -> None:
    e1 = build_envelope("PricesIngested", {"market": "NSE"})
    e2 = build_envelope("PricesIngested", {"market": "NSE"})
    assert set(e1) == {"event_id", "occurred_at", "topic", "version", "payload"}
    assert e1["topic"] == "PricesIngested" and e1["payload"] == {"market": "NSE"}
    assert e1["version"] == 1
    assert e1["event_id"] != e2["event_id"]  # unique per publish
    assert "T" in e1["occurred_at"]  # iso8601


def test_publish_dispatches_envelope_to_all_handlers_in_order() -> None:
    bus = InProcessEventBus()
    seen: list[tuple[str, dict[str, object]]] = []
    bus.subscribe("PricesValidated", lambda env: seen.append(("a", env)))
    bus.subscribe("PricesValidated", lambda env: seen.append(("b", env)))
    bus.publish("PricesValidated", {"market": "NSE", "n": 5})
    assert [h for h, _ in seen] == ["a", "b"]  # subscription order
    env = seen[0][1]
    assert env["topic"] == "PricesValidated" and env["payload"] == {"market": "NSE", "n": 5}


def test_no_handlers_is_a_noop() -> None:
    InProcessEventBus().publish("Unheard", {"x": 1})  # must not raise


def test_handler_error_is_isolated() -> None:
    bus = InProcessEventBus()
    got: list[int] = []

    def boom(_env: dict[str, object]) -> None:
        raise RuntimeError("handler down")

    bus.subscribe("T", boom)
    bus.subscribe("T", lambda _env: got.append(1))
    bus.publish("T", {})  # must not raise despite the first handler failing
    assert got == [1]  # sibling still ran


def test_get_event_bus_is_a_singleton_for_in_process() -> None:
    assert get_event_bus() is get_event_bus()
    assert isinstance(get_event_bus(), InProcessEventBus)


def test_factory_selects_the_configured_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    from quantvista.core import config
    from quantvista.core.events import KafkaEventBus, RedisStreamEventBus

    for backend, cls in [("redis_streams", RedisStreamEventBus), ("kafka", KafkaEventBus)]:
        monkeypatch.setattr(config.get_settings(), "event_bus_backend", backend)
        reset_event_bus()  # construction is lazy — no broker contact here
        assert isinstance(get_event_bus(), cls)
    reset_event_bus()


def test_factory_rejects_unknown_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    from quantvista.core import config

    monkeypatch.setattr(config.get_settings(), "event_bus_backend", "carrier-pigeon")
    reset_event_bus()
    with pytest.raises(ValueError, match="carrier-pigeon"):
        get_event_bus()


def test_logging_event_bus_publishes_without_error() -> None:
    from quantvista.core.events import LoggingEventBus

    LoggingEventBus().publish("X", {"a": 1})  # logs; must not raise
