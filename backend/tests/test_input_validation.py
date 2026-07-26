"""Input-validation hardening tests (QV-079).

Request-body schemas set ``extra="forbid"`` so unknown fields are rejected with a 422 rather than
silently ignored (OWASP ASVS V5.1 — mass-assignment / typo defense). This is DB-free: the
validation fires before any service/DB call.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from quantvista.schemas.auth import LoginRequest, RegisterRequest
from quantvista.schemas.portfolios import CreatePortfolioRequest
from quantvista.schemas.rebalance import RebalanceRequest


def test_register_request_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        RegisterRequest(email="a@b.com", password="x" * 12, is_admin=True)  # type: ignore[call-arg]


def test_login_request_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        LoginRequest(email="a@b.com", password="x" * 12, role="owner")  # type: ignore[call-arg]


def test_create_portfolio_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        CreatePortfolioRequest(name="p", tenant_id="sneaky")  # type: ignore[call-arg]


def test_rebalance_request_rejects_unknown_field() -> None:
    # drift_threshold has a default; the unknown `override` field is what must be rejected.
    with pytest.raises(ValidationError):
        RebalanceRequest(override="yes")  # type: ignore[call-arg]
