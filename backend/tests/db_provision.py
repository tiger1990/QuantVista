"""Per-run test database provisioning.

Gives every test run (and every xdist worker) its OWN database, so the suite stops mutating shared
state. This is the cure for what the session advisory lock only contained: tests that create and
drop partitions of ``daily_prices``, seed and delete reference rows, and previously wiped real
``jobs_runs`` history out of a developer's dev database.

Why a whole database rather than a transaction or a schema:

* **Not a transaction.** The code under test opens its OWN connections --
  ``privileged_session_scope`` builds an engine from ``get_settings()`` (``core/db.py``). Data
  written inside a test-held transaction would be invisible to them, so the classic
  rollback-per-test pattern cannot work here without refactoring production connections.
* **Not a schema.** Partitioned tables, RLS policies and Alembic all assume the default schema;
  threading a ``search_path`` through every engine buys nothing a separate database does not.

A database swap needs only the URL, which the application already reads from settings -- so this
requires no production change at all.

Cost is kept low with a TEMPLATE database: migrations + grants + seed are applied ONCE into
``quantvista_tmpl_<fingerprint>``, and each run is a ``CREATE DATABASE ... TEMPLATE`` file copy.
The fingerprint hashes the migration files and the seed, so the template rebuilds itself exactly
when the schema changes and never goes stale.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import create_engine, text

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_DB_DIR = _BACKEND_ROOT / "src" / "quantvista" / "db"
_VERSIONS_DIR = _DB_DIR / "migrations" / "versions"
_SEED_SQL = _DB_DIR / "seeds" / "seed_reference.sql"
# scripts/db/00-create-app-role.sql cannot be reused here: it is an initdb hook with an
# unconditional CREATE ROLE and a GRANT CONNECT hardcoded to the `quantvista` database. This is the
# idempotent equivalent -- the role is cluster-level, so it normally already exists.
_APP_ROLE_SQL = """
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quantvista_app') THEN
        CREATE ROLE quantvista_app WITH LOGIN PASSWORD 'quantvista_app'
            NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
    END IF;
END $$;
"""

# Connecting to create/drop a database requires being attached to a DIFFERENT one.
_MAINTENANCE_DB = "postgres"

# Mirrors the CI job's grant step so the template matches what CI provisions by hand.
_GRANT_SQL = """
GRANT USAGE ON SCHEMA public TO quantvista_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO quantvista_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO quantvista_app;
"""


class ProvisioningUnavailable(RuntimeError):
    """Raised when a per-run database cannot be created (missing privilege, old server, ...)."""


def with_database(url: str, dbname: str) -> str:
    """Return ``url`` pointing at ``dbname``, preserving driver, credentials, host and query."""
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path=f"/{dbname}"))


def schema_fingerprint() -> str:
    """Hash everything that determines the template's contents.

    Migrations AND the seed: a changed seed with unchanged migrations must still rebuild, or runs
    silently inherit stale reference data. Hashing content (not mtime) keeps this stable across
    checkouts and CI caches.
    """
    digest = hashlib.sha256()
    for path in sorted(_VERSIONS_DIR.glob("*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    digest.update(_SEED_SQL.read_bytes())
    return digest.hexdigest()[:12]


def template_name() -> str:
    return f"quantvista_tmpl_{schema_fingerprint()}"


def _maintenance_conn(admin_url: str):  # type: ignore[no-untyped-def]
    """AUTOCOMMIT connection to the maintenance DB (CREATE/DROP DATABASE cannot run in a tx)."""
    engine = create_engine(
        with_database(admin_url, _MAINTENANCE_DB), isolation_level="AUTOCOMMIT", future=True
    )
    return engine.connect()


def _database_exists(admin_url: str, name: str) -> bool:
    with _maintenance_conn(admin_url) as conn:
        found = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": name}
        ).scalar_one_or_none()
    return found is not None


def drop_database(admin_url: str, name: str) -> None:
    """Drop ``name``, disconnecting any stragglers (WITH FORCE needs PostgreSQL 13+)."""
    with _maintenance_conn(admin_url) as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


def _run_sql(url: str, sql: str) -> None:
    engine = create_engine(url, isolation_level="AUTOCOMMIT", future=True)
    with engine.connect() as conn:
        conn.exec_driver_sql(sql)
    engine.dispose()


def _apply_migrations(url: str) -> None:
    """Run Alembic exactly as CI does: from the db package, with DATABASE_URL as the admin URL."""
    result = subprocess.run(  # noqa: S603 -- fixed argv, no shell
        ["alembic", "upgrade", "head"],  # noqa: S607
        cwd=_DB_DIR,
        env={**os.environ, "DATABASE_URL": url},
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise ProvisioningUnavailable(
            f"alembic upgrade head failed:\n{result.stdout[-2000:]}\n{result.stderr[-2000:]}"
        )


def ensure_template(admin_url: str) -> str:
    """Create the template database for the current schema fingerprint if it does not exist.

    Built under a TEMPORARY name and renamed only on success, so an interrupted build can never
    leave a half-migrated template that later runs would silently copy.
    """
    name = template_name()
    if _database_exists(admin_url, name):
        return name

    building = f"{name}_building"
    with _maintenance_conn(admin_url) as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{building}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{building}"'))

    try:
        target = with_database(admin_url, building)
        _run_sql(with_database(admin_url, _MAINTENANCE_DB), _APP_ROLE_SQL)  # cluster-level
        _apply_migrations(target)
        # Table/sequence grants live in the database's own catalog, so the TEMPLATE copy carries
        # them to every run database for free.
        _run_sql(target, _GRANT_SQL)
        _run_sql(target, _SEED_SQL.read_text(encoding="utf-8"))
    except Exception:
        with _maintenance_conn(admin_url) as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{building}" WITH (FORCE)'))
        raise

    with _maintenance_conn(admin_url) as conn:
        # A concurrent run may have won the race; its template is equivalent, so keep it.
        if _database_exists(admin_url, name):
            conn.execute(text(f'DROP DATABASE IF EXISTS "{building}" WITH (FORCE)'))
        else:
            conn.execute(text(f'ALTER DATABASE "{building}" RENAME TO "{name}"'))
    return name


def create_run_database(admin_url: str, run_id: str) -> str:
    """Create this run's database from the template and return its name."""
    template = ensure_template(admin_url)
    name = f"quantvista_test_{run_id}"
    with _maintenance_conn(admin_url) as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{name}" TEMPLATE "{template}"'))
        # datacl is a property of the new database, not copied from the template.
        conn.execute(text(f'GRANT CONNECT ON DATABASE "{name}" TO quantvista_app'))
    return name


__all__ = [
    "ProvisioningUnavailable",
    "create_run_database",
    "drop_database",
    "ensure_template",
    "schema_fingerprint",
    "template_name",
    "with_database",
]
