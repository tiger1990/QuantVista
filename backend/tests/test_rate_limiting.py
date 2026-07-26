"""Per-IP rate-limiting tests (QV-079).

DB-free. The limiter is OFF by default (so the rest of the suite is unaffected — every
``TestClient`` request shares the constant key ``"testclient"``). This module flips it on via a
fixture that also resets storage, exercises the auth-endpoint limits, and asserts the 429 comes
back in the project envelope with a ``Retry-After`` header.

Uses ``raise_server_exceptions=False`` so the first N (pre-limit) calls don't need a DB — we only
assert the response *after* the limit is a 429 produced by slowapi before the route body runs.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from quantvista.api.app import create_app
from quantvista.api.ratelimit import RATE_LIMITS, limiter


@pytest.fixture
def rate_limited() -> Iterator[None]:
    """Enable the module-global limiter + reset storage; restore + reset on teardown."""
    limiter.enabled = True
    limiter.reset()
    yield
    limiter.enabled = False
    limiter.reset()


def _client() -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=False)


def test_limiter_disabled_by_default() -> None:
    # Guards the whole suite: with the default settings the limiter must be off.
    assert limiter.enabled is False


def test_login_rate_limit_returns_429_envelope(rate_limited: None) -> None:
    client = _client()
    limit = int(RATE_LIMITS["login"].split("/")[0])  # "10/minute" -> 10
    for _ in range(limit):
        client.post("/api/v1/auth/login", json={"email": "x@x.com", "password": "nope"})
    r = client.post("/api/v1/auth/login", json={"email": "x@x.com", "password": "nope"})
    assert r.status_code == 429
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "rate_limited"
    assert "retry-after" in {k.lower() for k in r.headers}


def test_register_rate_limit_trips_after_five(rate_limited: None) -> None:
    client = _client()
    limit = int(RATE_LIMITS["register"].split("/")[0])  # "5/minute" -> 5
    statuses = [
        client.post(
            "/api/v1/auth/register", json={"email": f"a{i}@x.com", "password": "x" * 12}
        ).status_code
        for i in range(limit + 1)
    ]
    assert statuses[-1] == 429  # the (limit+1)-th request is blocked
    assert statuses.count(429) == 1  # only the last one


def test_within_limit_is_not_rate_limited(rate_limited: None) -> None:
    client = _client()
    # A single refresh call (limit 30/min) is well within the window — never 429.
    r = client.post("/api/v1/auth/refresh")
    assert r.status_code != 429
