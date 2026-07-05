"""Event-driven pipeline consumers (QV-025) — the first real subscribers.

Wires both edges of the ingest→validate→indicators DAG onto the shared event bus (QV-024). The
handlers are **thin**: they ``.delay()`` the corresponding Celery task so heavy work runs in the
worker, not inside the (synchronous, in-process) publish. Registered at worker start.

    PricesIngested    ─▶ validate_prices        ─▶ PricesValidated / DataQualityGateFailed
    PricesValidated   ─▶ compute_indicators     ─▶ IndicatorsComputed
    IndicatorsComputed ─▶ compute_factors        ─▶ FactorsComputed
    FactorsComputed   ─▶ compute_scores          ─▶ ScoresComputed
    FundamentalsRevised ─▶ recompute_on_correction (self-heal, QV-027 / 06 §5)
"""

from __future__ import annotations

from typing import Any

import structlog

from quantvista.core.interfaces import IEventBus
from quantvista.jobs.compute import compute_indicators
from quantvista.jobs.corrections import recompute_on_correction
from quantvista.jobs.ingest import ingest_daily_prices  # noqa: F401  (task registry side-effect)
from quantvista.jobs.quality import validate_prices
from quantvista.jobs.scoring import compute_factors, compute_scores

_log = structlog.get_logger()


def on_prices_ingested(envelope: dict[str, Any]) -> None:
    """Raw prices landed → run the data-quality gate."""
    payload = envelope["payload"]
    _log.info("consume_prices_ingested", market=payload["market"], date=payload["end"])
    validate_prices.delay(payload["market"], payload["end"])


def on_prices_validated(envelope: dict[str, Any]) -> None:
    """Gate passed → compute technical indicators."""
    payload = envelope["payload"]
    _log.info("consume_prices_validated", market=payload["market"], date=payload["end"])
    compute_indicators.delay(payload["market"], payload["end"])


def on_indicators_computed(envelope: dict[str, Any]) -> None:
    """Fresh indicators → recompute the factor snapshot."""
    payload = envelope["payload"]
    _log.info("consume_indicators_computed", market=payload["market"], date=payload["date"])
    compute_factors.delay(payload["market"], payload["date"])


def on_factors_computed(envelope: dict[str, Any]) -> None:
    """Fresh factor snapshot → project it into scores."""
    payload = envelope["payload"]
    _log.info("consume_factors_computed", market=payload["market"], date=payload["date"])
    compute_scores.delay(payload["market"], payload["date"])


def on_fundamentals_revised(envelope: dict[str, Any]) -> None:
    """A fundamentals correction landed → recompute derived analytics for each affected filing."""
    payload = envelope["payload"]
    for rev in payload["revisions"]:
        _log.info(
            "consume_fundamentals_revised",
            stock_id=rev["stock_id"],
            period_end=rev["period_end"],
        )
        recompute_on_correction.delay(rev["stock_id"], rev["period_end"], rev["statement_type"])


def register_pipeline_consumers(bus: IEventBus) -> None:
    """Subscribe the pipeline handlers on ``bus`` (idempotent-ish — call once at worker start)."""
    bus.subscribe("PricesIngested", on_prices_ingested)
    bus.subscribe("PricesValidated", on_prices_validated)
    bus.subscribe("IndicatorsComputed", on_indicators_computed)
    bus.subscribe("FactorsComputed", on_factors_computed)
    bus.subscribe("FundamentalsRevised", on_fundamentals_revised)
