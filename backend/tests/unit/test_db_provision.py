"""Unit tests for the per-run test-database helpers (no database required).

Only the pure parts are covered here: URL rewriting and the template fingerprint. The
provisioning itself (CREATE DATABASE ... TEMPLATE) is exercised every time the integration
suite runs -- if it broke, nothing would run at all.
"""

from __future__ import annotations

from tests.db_provision import schema_fingerprint, template_name, with_database


class TestWithDatabase:
    def test_swaps_the_database_only(self) -> None:
        url = "postgresql+psycopg://user:pw@localhost:5432/quantvista"
        assert (
            with_database(url, "qv_test_1")
            == "postgresql+psycopg://user:pw@localhost:5432/qv_test_1"
        )

    def test_preserves_credentials_port_and_driver(self) -> None:
        out = with_database("postgresql+psycopg://u:p@db.internal:6543/orig", "copy")
        assert out.startswith("postgresql+psycopg://u:p@db.internal:6543/")
        assert out.endswith("/copy")

    def test_preserves_query_parameters(self) -> None:
        """sslmode and friends must survive, or a swapped URL silently loses TLS settings."""
        out = with_database("postgresql+psycopg://u:p@h:5432/orig?sslmode=require", "copy")
        assert out == "postgresql+psycopg://u:p@h:5432/copy?sslmode=require"


class TestFingerprint:
    def test_is_stable_across_calls(self) -> None:
        assert schema_fingerprint() == schema_fingerprint()

    def test_template_name_embeds_the_fingerprint(self) -> None:
        assert template_name() == f"quantvista_tmpl_{schema_fingerprint()}"

    def test_is_a_short_hex_digest(self) -> None:
        fp = schema_fingerprint()
        assert len(fp) == 12
        assert all(c in "0123456789abcdef" for c in fp)
