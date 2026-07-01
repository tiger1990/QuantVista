"""DB-free unit tests for auth security primitives (quantvista.identity.security)."""

from __future__ import annotations

import time
from uuid import uuid4

import jwt
import pytest

from quantvista.core.config import get_settings
from quantvista.identity import security


def test_password_hash_is_not_plaintext_and_verifies() -> None:
    h = security.hash_password("hunter2-correct-horse")
    assert h != "hunter2-correct-horse"
    assert "argon2" in h  # argon2id encoded hash
    assert security.verify_password(h, "hunter2-correct-horse") is True
    assert security.verify_password(h, "wrong-password") is False


def test_access_token_round_trip_carries_claims() -> None:
    uid, tid = uuid4(), uuid4()
    token = security.create_access_token(uid, tid, "owner")
    claims = security.decode_access_token(token)
    assert claims["sub"] == str(uid)
    assert claims["tenant_id"] == str(tid)
    assert claims["role"] == "owner"
    assert claims["type"] == "access"


def test_valid_signature_but_missing_claim_is_unauthenticated() -> None:
    # Arrange — a correctly-SIGNED token that omits the required tenant_id claim must be
    # rejected as unauthenticated, never crash with an unhandled KeyError (→ 500).
    from types import SimpleNamespace

    from quantvista.api.deps import get_current_principal
    from quantvista.identity.models import InvalidCredentials

    settings = get_settings()
    forged = jwt.encode(
        {"sub": str(uuid4()), "role": "owner"},  # no tenant_id
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    request = SimpleNamespace(
        headers={"Authorization": f"Bearer {forged}"}, state=SimpleNamespace()
    )
    # Act / Assert
    with pytest.raises(InvalidCredentials):
        get_current_principal(request)  # type: ignore[arg-type]


def test_expired_access_token_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACCESS_TOKEN_TTL_SECONDS", "1")
    get_settings.cache_clear()
    try:
        token = security.create_access_token(uuid4(), uuid4(), "owner")
        time.sleep(2)
        with pytest.raises(jwt.ExpiredSignatureError):
            security.decode_access_token(token)
    finally:
        get_settings.cache_clear()


def test_refresh_token_is_opaque_and_hash_is_stable() -> None:
    raw, h = security.new_refresh_token()
    assert raw and raw != h
    assert h == security.hash_refresh_token(raw)
    assert len(h) == 64  # sha256 hex
