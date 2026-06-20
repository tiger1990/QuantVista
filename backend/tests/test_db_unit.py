"""DB-free unit tests for the session layer (no PostgreSQL required)."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from quantvista.core.db import _SET_TENANT_SQL, bind_tenant


def test_bind_tenant_emits_local_set_config() -> None:
    # Arrange
    session = MagicMock()
    tenant_id = uuid4()

    # Act
    bind_tenant(session, tenant_id)

    # Assert — parameterized, transaction-local set_config with the tenant as a string
    session.execute.assert_called_once_with(_SET_TENANT_SQL, {"tid": str(tenant_id)})
    assert "set_config('app.tenant_id'" in str(_SET_TENANT_SQL)
    assert "true" in str(_SET_TENANT_SQL)  # local/transaction scope
