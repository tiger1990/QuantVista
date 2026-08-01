"""Database maintenance jobs (QV-104) — keep monthly partitions ahead of the data.

The migrations bootstrap only the current and next month; `db/README.md` always said the rest was a
*scheduled* concern, but no schedule existed. Without one, PostgreSQL silently routes rows into each
table's ``_default`` partition once the pre-created months run out — no error, no alert, just lost
pruning and an unbounded default table. This task closes that gap.

It runs **daily**, not monthly: the work is idempotent and trivially cheap (``CREATE TABLE IF NOT
EXISTS`` per parent-month), so a daily tick means a missed run, a failed worker, or a restart on the
wrong day all self-heal by the next day instead of waiting a month for the next chance.
"""

from __future__ import annotations

import structlog

from quantvista.core.db import privileged_session_scope
from quantvista.core.partitions import DEFAULT_MONTHS_AHEAD, ensure_month_partitions
from quantvista.jobs.celery_app import app

log = structlog.get_logger(__name__)


@app.task(
    name="quantvista.ensure_partitions",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def ensure_partitions(months_ahead: int = DEFAULT_MONTHS_AHEAD) -> str:
    """Ensure every date-range-partitioned table has partitions for the coming months.

    Runs on the privileged session: partition DDL is a global/reference concern, not tenant-scoped.
    """
    with privileged_session_scope() as session:
        result = ensure_month_partitions(session, months_ahead=months_ahead)
    log.info(
        "partitions_ensured",
        parents=len(result.parents),
        months=len(result.months),
        through=result.months[-1].isoformat() if result.months else None,
    )
    return "ok"


__all__ = ["ensure_partitions"]
