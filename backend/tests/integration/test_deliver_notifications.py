"""Notification delivery end-to-end (QV-049) — real PG. Seeds fired alert_events on rules of each
channel, then delivers: in-app writes a notifications row, email hits the injected sender, the
rule's channel is honored, a failing sender marks the event failed and a re-run retries it.
Cross-tenant via the privileged session. Users/tenants cleaned up (rules/events/notifications)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, text

from quantvista.alerts.services import NotificationDeliveryService

pytestmark = pytest.mark.integration
_PAYLOAD = {"metric": "composite_score", "op": "lt", "threshold": 50, "value": 40}


class _SpySender:
    def __init__(self) -> None:
        self.sent: list[str] = []

    def send(self, *, to: str, subject: str, body: str) -> None:
        self.sent.append(to)


class _FailSender:
    def send(self, *, to: str, subject: str, body: str) -> None:
        raise RuntimeError("smtp down")


def _seed_user(conn: object, email: str) -> tuple[UUID, UUID, UUID]:
    """A tenant + user + membership (bypassing auth); returns (tenant_id, user_id, spare)."""
    tenant_id, user_id = uuid4(), uuid4()
    conn.execute(  # type: ignore[attr-defined]
        text("INSERT INTO tenants (id, name) VALUES (:id, :n)"),
        {"id": tenant_id, "n": f"T-{email}"},
    )
    conn.execute(  # type: ignore[attr-defined]
        text("INSERT INTO users (id, email, password_hash) VALUES (:id, :e, 'x')"),
        {"id": user_id, "e": email},
    )
    conn.execute(  # type: ignore[attr-defined]
        text(
            "INSERT INTO memberships (id, tenant_id, user_id, role) "
            "VALUES (gen_random_uuid(), :t, :u, 'owner')"
        ),
        {"t": tenant_id, "u": user_id},
    )
    return tenant_id, user_id, uuid4()


def _seed_event(conn: object, tenant_id: UUID, user_id: UUID, channel: str) -> UUID:
    rule_id, event_id = uuid4(), uuid4()
    conn.execute(  # type: ignore[attr-defined]
        text(
            "INSERT INTO alert_rules "
            "(id, tenant_id, user_id, scope, target_id, condition, channel) "
            "VALUES (:id, :t, :u, 'stock', :tg, CAST(:c AS jsonb), :ch)"
        ),
        {
            "id": rule_id,
            "t": tenant_id,
            "u": user_id,
            "tg": uuid4(),
            "c": json.dumps(_PAYLOAD),
            "ch": channel,
        },
    )
    conn.execute(  # type: ignore[attr-defined]
        text(
            "INSERT INTO alert_events (id, tenant_id, alert_rule_id, dedup_key, payload, status) "
            "VALUES (:id, :t, :r, '2026-07-12', CAST(:p AS jsonb), 'pending')"
        ),
        {"id": event_id, "t": tenant_id, "r": rule_id, "p": json.dumps(_PAYLOAD)},
    )
    return event_id


def _status(admin_engine: Engine, event_id: UUID) -> tuple[str, bool]:
    with admin_engine.connect() as conn:
        r = conn.execute(
            text("SELECT status, delivered_at IS NOT NULL FROM alert_events WHERE id = :id"),
            {"id": event_id},
        ).one()
    return str(r[0]), bool(r[1])


@pytest.fixture
def emails() -> Iterator[list[str]]:
    yield [f"qv-{uuid4()}@test.local" for _ in range(2)]


@pytest.fixture(autouse=True)
def _cleanup(admin_engine: Engine, emails: list[str]) -> Iterator[None]:
    yield
    with admin_engine.begin() as conn:
        for email in emails:  # tenant delete cascades rules/events/notifications
            conn.execute(
                text(
                    "DELETE FROM tenants WHERE id IN (SELECT tenant_id FROM memberships m "
                    "JOIN users u ON u.id = m.user_id WHERE u.email = :e)"
                ),
                {"e": email},
            )
            conn.execute(text("DELETE FROM users WHERE email = :e"), {"e": email})


def test_in_app_writes_notification_and_marks_delivered(
    admin_engine: Engine, emails: list[str]
) -> None:
    with admin_engine.begin() as conn:
        tenant_id, user_id, _ = _seed_user(conn, emails[0])
        event_id = _seed_event(conn, tenant_id, user_id, "in_app")

    delivered = NotificationDeliveryService().deliver_pending()
    assert delivered >= 1
    assert _status(admin_engine, event_id) == ("delivered", True)
    with admin_engine.connect() as conn:
        n = conn.execute(
            text("SELECT count(*) FROM notifications WHERE user_id = :u AND type = 'alert'"),
            {"u": user_id},
        ).scalar_one()
    assert n == 1


def test_email_channel_uses_sender_and_is_honored(admin_engine: Engine, emails: list[str]) -> None:
    with admin_engine.begin() as conn:
        t_a, u_a, _ = _seed_user(conn, emails[0])
        t_b, u_b, _ = _seed_user(conn, emails[1])
        email_event = _seed_event(conn, t_a, u_a, "email")
        inapp_event = _seed_event(conn, t_b, u_b, "in_app")

    spy = _SpySender()
    NotificationDeliveryService(email_sender=spy).deliver_pending()

    assert spy.sent == [emails[0]]  # only the email-channel rule hit the sender
    assert _status(admin_engine, email_event)[0] == "delivered"
    assert _status(admin_engine, inapp_event)[0] == "delivered"
    with admin_engine.connect() as conn:  # in-app went to the notifications table, not email
        assert (
            conn.execute(
                text("SELECT count(*) FROM notifications WHERE user_id = :u"), {"u": u_b}
            ).scalar_one()
            == 1
        )


def test_failed_delivery_is_marked_and_retried(admin_engine: Engine, emails: list[str]) -> None:
    with admin_engine.begin() as conn:
        tenant_id, user_id, _ = _seed_user(conn, emails[0])
        event_id = _seed_event(conn, tenant_id, user_id, "email")

    assert NotificationDeliveryService(email_sender=_FailSender()).deliver_pending() == 0
    assert _status(admin_engine, event_id) == ("failed", False)  # marked failed, not delivered

    # a later run re-attempts failed events (the retry) with a working sender
    spy = _SpySender()
    assert NotificationDeliveryService(email_sender=spy).deliver_pending() >= 1
    assert spy.sent == [emails[0]]
    assert _status(admin_engine, event_id) == ("delivered", True)
