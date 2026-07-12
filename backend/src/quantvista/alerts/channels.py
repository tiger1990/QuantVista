"""Notification channels (QV-049) — how a fired alert reaches a user.

``InAppChannel`` writes a ``notifications`` row (0010); ``EmailChannel`` hands off to an
``IEmailSender``. The real SES/Resend sender is deferred (no creds in dev — same posture as AWS);
dev/CI use ``LogEmailSender``, which logs the send and counts as delivered. Each channel is
constructed with what it needs (a session / a sender) and exposes the uniform ``deliver(target)``.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from quantvista.alerts.email import IEmailSender
from quantvista.alerts.interfaces import DeliveryTarget
from quantvista.alerts.repositories import insert_notification

NOTIFICATION_TYPE = "alert"


class InAppChannel:
    """In-app delivery — persists a ``notifications`` row for the user (0010)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def deliver(self, target: DeliveryTarget) -> None:
        insert_notification(
            self._session,
            tenant_id=target.tenant_id,
            user_id=target.user_id,
            type=NOTIFICATION_TYPE,
            payload=target.payload,
        )


class EmailChannel:
    """Email delivery via the injected sender (``LogEmailSender`` in dev)."""

    def __init__(self, sender: IEmailSender) -> None:
        self._sender = sender

    def deliver(self, target: DeliveryTarget) -> None:
        self._sender.send(
            to=target.email,
            subject=_subject(target.payload),
            body=_body(target.payload),
        )


def _subject(payload: dict[str, Any]) -> str:
    metric = payload.get("metric", "alert")
    return f"QuantVista alert: {metric} {payload.get('op', '')} {payload.get('threshold', '')}"


def _body(payload: dict[str, Any]) -> str:
    return (
        f"An alert you configured fired: {payload.get('metric')} is {payload.get('value')} "
        f"({payload.get('op')} {payload.get('threshold')})."
    )
