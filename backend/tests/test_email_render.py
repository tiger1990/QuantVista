"""Unit tests for the branded alert-email renderer (email_render, QV-049 enhancement) — no I/O.

Pins the fires-today ``metric_alert`` template (real content, humanized labels, CTA/manage links,
disclaimer), the wordmark ↔ hosted-logo switch, autoescaping of injected payload values, the value
formatter, and that the scaffold event types render valid HTML + fall back safely.
"""

from __future__ import annotations

import pytest

from quantvista.alerts.email_render import DISCLAIMER, _fmt, render_email
from quantvista.core.config import Settings

_APP = "https://app.quantvista.example"


def _settings(**over: object) -> Settings:
    return Settings(app_base_url=_APP, email_from_name="QuantVista Alerts", **over)  # type: ignore[arg-type]


def _metric_payload(**over: object) -> dict[str, object]:
    base = {
        "type": "metric_alert",
        "symbol": "RELIANCE",
        "company_name": "Reliance Industries Ltd",
        "metric": "composite_score",
        "op": "gte",
        "threshold": 70,
        "value": 72.4,
    }
    return {**base, **over}


def test_metric_alert_subject_and_core_content() -> None:
    subject, html = render_email(_metric_payload(), settings=_settings())

    assert subject == "QuantVista alert: RELIANCE Composite score ≥ 70"
    assert "RELIANCE" in html
    assert "Reliance Industries Ltd" in html
    assert "Composite score" in html  # humanized, not the raw metric key
    assert "composite_score" not in html
    assert "72.4" in html  # current value
    assert "≥ 70" in html  # condition in the card
    assert DISCLAIMER in html


def test_metric_alert_links_use_app_base_url() -> None:
    _, html = render_email(_metric_payload(), settings=_settings())
    assert f'href="{_APP}/stocks/RELIANCE"' in html  # CTA → stock page
    assert f'href="{_APP}/alerts"' in html  # footer → manage alerts


def test_wordmark_by_default_and_hosted_logo_when_configured() -> None:
    _, plain = render_email(_metric_payload(), settings=_settings())
    assert "QUANT" in plain and "VISTA" in plain
    assert "<img" not in plain

    _, withlogo = render_email(
        _metric_payload(), settings=_settings(email_logo_url="https://cdn.example/logo.png")
    )
    assert '<img src="https://cdn.example/logo.png"' in withlogo


def test_injected_payload_values_are_escaped() -> None:
    _, html = render_email(
        _metric_payload(company_name="<script>alert(1)</script>"), settings=_settings()
    )
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_unknown_type_falls_back_to_metric_alert() -> None:
    subject, html = render_email(_metric_payload(type="totally-unknown"), settings=_settings())
    assert subject.startswith("QuantVista alert:")
    assert "Composite score" in html


@pytest.mark.parametrize("alert_type", ["earnings", "ipo", "dividend"])
def test_scaffold_event_types_render_valid_html(alert_type: str) -> None:
    payload = {
        "type": alert_type,
        "symbol": "TCS",
        "company_name": "Tata Consultancy",
        "event_date": "2026-07-18",
    }
    subject, html = render_email(payload, settings=_settings())
    assert subject.startswith("QuantVista")
    assert html.startswith("<!DOCTYPE html>") and html.rstrip().endswith("</html>")
    assert DISCLAIMER in html
    assert "2026-07-18" in html


@pytest.mark.parametrize(
    ("value", "expected"),
    [(70.0, "70"), (72.4, "72.4"), (14.35, "14.35"), (0.85, "0.85"), (None, "—")],
)
def test_fmt(value: object, expected: str) -> None:
    assert _fmt(value) == expected


def test_email_channel_sends_rendered_html() -> None:
    """EmailChannel renders the branded HTML from the payload and hands it to the sender as-is."""
    from uuid import uuid4

    from quantvista.alerts.channels import EmailChannel
    from quantvista.alerts.interfaces import DeliveryTarget

    captured: dict[str, str] = {}

    class _Spy:
        def send(self, *, to: str, subject: str, body: str) -> None:
            captured.update(to=to, subject=subject, body=body)

    target = DeliveryTarget(
        tenant_id=uuid4(), user_id=uuid4(), email="user@test.local", payload=_metric_payload()
    )
    EmailChannel(_Spy()).deliver(target)

    assert captured["to"] == "user@test.local"
    assert captured["subject"].startswith("QuantVista alert: RELIANCE")
    assert captured["body"].startswith("<!DOCTYPE html>")
    assert "RELIANCE" in captured["body"]
