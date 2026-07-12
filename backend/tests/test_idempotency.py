"""Unit tests for the request fingerprint (api.idempotency, QV-052) — pure, no DB.

The fingerprint identifies a mutating request so a replay under the same ``Idempotency-Key`` can be
told apart from key-reuse-with-a-different-body (→ 409). It must be stable across dict key order and
sensitive to method / path / body content.
"""

from __future__ import annotations

from quantvista.api.idempotency import fingerprint


def test_same_request_same_fingerprint() -> None:
    a = fingerprint("POST", "/api/v1/portfolios", {"name": "Growth", "benchmark": "NIFTY200_TRI"})
    b = fingerprint("POST", "/api/v1/portfolios", {"name": "Growth", "benchmark": "NIFTY200_TRI"})
    assert a == b


def test_key_order_does_not_matter() -> None:
    a = fingerprint("POST", "/api/v1/portfolios", {"name": "Growth", "benchmark": "NIFTY200_TRI"})
    b = fingerprint("POST", "/api/v1/portfolios", {"benchmark": "NIFTY200_TRI", "name": "Growth"})
    assert a == b


def test_different_body_differs() -> None:
    a = fingerprint("POST", "/api/v1/portfolios", {"name": "Growth"})
    b = fingerprint("POST", "/api/v1/portfolios", {"name": "Value"})
    assert a != b


def test_different_path_differs() -> None:
    a = fingerprint("POST", "/api/v1/portfolios", {"name": "Growth"})
    b = fingerprint("POST", "/api/v1/other", {"name": "Growth"})
    assert a != b


def test_fingerprint_is_hex_digest() -> None:
    fp = fingerprint("POST", "/api/v1/portfolios", {"name": "Growth"})
    assert isinstance(fp, str) and len(fp) == 64  # sha-256 hex
