"""Branded HTML email rendering (QV-049 enhancement).

Turns a fired alert's ``payload`` into a ``(subject, html)`` pair using the Jinja templates in
``templates/email/``. The HTML is **provider-portable** — sent verbatim as ``htmlContent`` by any
``IEmailSender`` (Brevo now, SES later), so nothing is locked to a provider's stored templates.

Alert **types** are registered here. ``metric_alert`` is the only one that fires today: a factual
metric-threshold notice — no buy/sell call or price target (see the footer disclaimer). The
``earnings``/``ipo``/``dividend`` types are scaffolds: their templates + registry entries exist so
they're ready to light up once the event feeds that generate them are built (future stories).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from quantvista.core.config import Settings, get_settings

_TEMPLATE_DIR = Path(__file__).parent / "templates" / "email"
_ENV = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "j2"]),  # escape injected payload values
)

# Positioning line kept on every alert email — factual research signal, not investment advice.
DISCLAIMER = (
    "QuantVista provides quantitative research signals for informational purposes only. This is "
    "not investment advice, a recommendation, or an offer to buy or sell any security. Do your "
    "own research before acting."
)

# Human labels for the QV-047 allow-list metrics and comparison operators.
_METRIC_LABELS: dict[str, str] = {
    "composite_score": "Composite score",
    "fundamental_score": "Fundamental score",
    "momentum_score": "Momentum score",
    "quality_score": "Quality score",
    "sentiment_score": "Sentiment score",
    "risk_score": "Risk score",
    "coverage": "Data coverage",
    "pe": "P/E ratio",
    "pb": "P/B ratio",
    "roe": "Return on equity (ROE)",
    "roce": "Return on capital (ROCE)",
    "debt_equity": "Debt-to-equity",
}
_OP_SYMBOLS: dict[str, str] = {"gte": "≥", "lte": "≤", "gt": ">", "lt": "<", "eq": "="}
_OP_WORDS: dict[str, str] = {
    "gte": "at or above",
    "lte": "at or below",
    "gt": "above",
    "lt": "below",
    "eq": "at",
}


def _fmt(value: Any) -> str:
    """Format a metric/threshold for display: drop a trailing ``.0``, else keep up to 2 decimals."""
    if value is None:
        return "—"  # em dash
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    if num == int(num):
        return str(int(num))
    return f"{num:.2f}".rstrip("0").rstrip(".")


def _metric_content(payload: dict[str, Any], app_base_url: str) -> dict[str, Any]:
    symbol = payload.get("symbol") or ""
    metric = str(payload.get("metric", ""))
    op = str(payload.get("op", ""))
    return {
        "symbol": symbol or "your stock",
        "company_name": payload.get("company_name"),
        "metric_label": _METRIC_LABELS.get(metric, metric.replace("_", " ").capitalize()),
        "op_symbol": _OP_SYMBOLS.get(op, op),
        "op_words": _OP_WORDS.get(op, op),
        "value_display": _fmt(payload.get("value")),
        "threshold_display": _fmt(payload.get("threshold")),
        "cta_url": f"{app_base_url}/stocks/{symbol}" if symbol else app_base_url,
    }


def _metric_subject(ctx: dict[str, Any]) -> str:
    return (
        f"QuantVista alert: {ctx['symbol']} {ctx['metric_label']} "
        f"{ctx['op_symbol']} {ctx['threshold_display']}"
    )


def _event_content(payload: dict[str, Any], app_base_url: str, default_msg: str) -> dict[str, Any]:
    """Shared context builder for the scaffold event types (earnings/ipo/dividend)."""
    symbol = payload.get("symbol") or ""
    return {
        "symbol": symbol,
        "company_name": payload.get("company_name"),
        "event_date": payload.get("event_date"),
        "message": payload.get("message") or default_msg,
        "cta_url": f"{app_base_url}/stocks/{symbol}" if symbol else app_base_url,
    }


@dataclass(frozen=True)
class _AlertType:
    template: str
    build_content: Callable[[dict[str, Any], str], dict[str, Any]]
    build_subject: Callable[[dict[str, Any]], str]


# Registry: alert type → template + how to build its subject/content. New type = one entry + one
# ``.html.j2``; the metric type is the fires-today default (unknown types fall back to it).
_ALERT_TYPES: dict[str, _AlertType] = {
    "metric_alert": _AlertType("metric_alert.html.j2", _metric_content, _metric_subject),
    "earnings": _AlertType(
        "earnings_alert.html.j2",
        lambda p, url: _event_content(p, url, "Earnings are coming up for a stock you follow."),
        lambda ctx: f"QuantVista: {ctx['symbol'] or 'a stock you follow'} earnings coming up",
    ),
    "ipo": _AlertType(
        "ipo_alert.html.j2",
        lambda p, url: _event_content(p, url, "A new IPO is opening for subscription."),
        lambda ctx: f"QuantVista: {ctx.get('company_name') or ctx['symbol'] or 'new'} IPO",
    ),
    "dividend": _AlertType(
        "dividend_alert.html.j2",
        lambda p, url: _event_content(p, url, "There's a dividend update for a stock you follow."),
        lambda ctx: f"QuantVista: {ctx['symbol'] or 'a stock you follow'} dividend update",
    ),
}


def render_email(payload: dict[str, Any], *, settings: Settings | None = None) -> tuple[str, str]:
    """Render a fired alert ``payload`` into ``(subject, html)`` for the chosen alert type."""
    settings = settings or get_settings()
    alert_type = payload.get("type") or "metric_alert"
    spec = _ALERT_TYPES.get(alert_type, _ALERT_TYPES["metric_alert"])
    app_base_url = settings.app_base_url.rstrip("/")

    ctx: dict[str, Any] = {
        "from_name": settings.email_from_name,
        "logo_url": settings.email_logo_url,
        "disclaimer": DISCLAIMER,
        "manage_url": f"{app_base_url}/alerts",
    }
    ctx.update(spec.build_content(payload, app_base_url))
    subject = spec.build_subject(ctx)
    ctx["subject"] = subject
    # strip() drops the leading newlines the top-of-file {# … #} comments leave before <!DOCTYPE>.
    html = _ENV.get_template(spec.template).render(ctx).strip()
    return subject, html
