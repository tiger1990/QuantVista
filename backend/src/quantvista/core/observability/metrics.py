"""Prometheus metrics for the api and worker roles.

API exposes RED (Rate, Errors, Duration) per route *template* (bounded cardinality —
never the raw path) plus a per-tenant request-volume counter. The worker records task
count/latency/failures via Celery signals and, since it serves no HTTP, exposes its
registry on a small ``prometheus_client`` server. All of this is gated by
``metrics_enabled``; metric objects live on the default registry (process singletons).
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# --- API (RED) ---------------------------------------------------------------
HTTP_REQUESTS = Counter("http_requests_total", "HTTP requests", ["method", "route", "status"])
HTTP_ERRORS = Counter(
    "http_request_errors_total", "HTTP responses with status >= 500", ["method", "route"]
)
HTTP_LATENCY = Histogram(
    "http_request_duration_seconds", "HTTP request latency", ["method", "route"]
)
TENANT_REQUESTS = Counter("http_requests_by_tenant_total", "HTTP requests per tenant", ["tenant"])

# --- Worker ------------------------------------------------------------------
TASK_TOTAL = Counter("celery_tasks_total", "Celery tasks by terminal state", ["task", "state"])
TASK_LATENCY = Histogram("celery_task_duration_seconds", "Celery task latency", ["task"])
TASK_FAILURES = Counter("celery_task_failures_total", "Celery task failures", ["task"])

# --- Pipeline / job health (QV-020) ------------------------------------------
# Freshness is exported as a timestamp; lag = time() - gauge, derived in PromQL/Grafana so it
# never goes stale between scrapes. Queue depth is the pending-message backlog per queue.
DATA_FRESHNESS = Gauge(
    "data_latest_ingest_timestamp_seconds",
    "Unix timestamp of the newest ingested data point, per dataset",
    ["dataset"],
)
QUEUE_DEPTH = Gauge("celery_queue_depth", "Pending messages in a Celery/Redis queue", ["queue"])


def set_data_freshness(dataset: str, epoch_seconds: float) -> None:
    """Publish the freshness timestamp for ``dataset`` (thin setter; DB query lives in jobs)."""
    DATA_FRESHNESS.labels(dataset=dataset).set(epoch_seconds)


def set_queue_depth(queue: str, depth: int) -> None:
    """Publish the pending-message backlog for ``queue`` (thin setter; Redis call lives in jobs)."""
    QUEUE_DEPTH.labels(queue=queue).set(depth)


METRICS_PATH = "/metrics"

_Call = Callable[[Request], Awaitable[Response]]


def render_metrics() -> tuple[bytes, str]:
    """Return the Prometheus exposition payload + its content type."""
    return generate_latest(), CONTENT_TYPE_LATEST


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) else "unmatched"


class PrometheusMiddleware(BaseHTTPMiddleware):
    """Record RED + per-tenant metrics for every request except ``/metrics`` itself."""

    async def dispatch(self, request: Request, call_next: _Call) -> Response:
        if request.url.path == METRICS_PATH:
            return await call_next(request)

        method = request.method
        start = time.perf_counter()
        try:
            response = await call_next(request)
            status = response.status_code
        except Exception:
            _observe(request, method, 500)
            raise
        _observe(request, method, status, time.perf_counter() - start)
        return response


def _observe(request: Request, method: str, status: int, duration: float | None = None) -> None:
    route = _route_template(request)
    HTTP_REQUESTS.labels(method=method, route=route, status=str(status)).inc()
    if status >= 500:
        HTTP_ERRORS.labels(method=method, route=route).inc()
    if duration is not None:
        HTTP_LATENCY.labels(method=method, route=route).observe(duration)
    tenant = getattr(request.state, "tenant_id", None)
    if tenant:
        TENANT_REQUESTS.labels(tenant=str(tenant)).inc()


# --- Worker (Celery signals) -------------------------------------------------
_task_started_at: dict[str, float] = {}


def record_task_prerun(task_id: str | None = None, **_: Any) -> None:
    if task_id:
        _task_started_at[task_id] = time.perf_counter()


def record_task_postrun(
    task_id: str | None = None, task: Any = None, state: str | None = None, **_: Any
) -> None:
    name = getattr(task, "name", "unknown")
    TASK_TOTAL.labels(task=name, state=state or "UNKNOWN").inc()
    started = _task_started_at.pop(task_id, None) if task_id else None
    if started is not None:
        TASK_LATENCY.labels(task=name).observe(time.perf_counter() - started)


def record_task_failure(sender: Any = None, **_: Any) -> None:
    name = getattr(sender, "name", "unknown")
    TASK_FAILURES.labels(task=name).inc()


def install_worker_metrics() -> None:
    """Connect the Celery signal handlers (idempotent — signals dedupe by receiver)."""
    from celery.signals import task_failure, task_postrun, task_prerun

    task_prerun.connect(record_task_prerun, weak=False)
    task_postrun.connect(record_task_postrun, weak=False)
    task_failure.connect(record_task_failure, weak=False)


def start_worker_metrics_server(port: int) -> None:
    """Expose the default registry over HTTP for Prometheus scraping (worker role)."""
    from prometheus_client import start_http_server

    start_http_server(port)
