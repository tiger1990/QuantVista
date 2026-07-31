"""Every tenant-session write route must commit before its response is sent.

FastAPI finalises ``yield`` dependencies *after* the response goes out, and that is where
``get_tenant_session`` commits. Without ``CommitBeforeResponseRoute`` a client that mutates and
immediately re-reads can be served pre-commit state — the bug where a deleted row stayed in the
history list. Measured on the live server: 1/6 stale reads without the route class, 0/12 with it.

This is a structural guard: a new router that forgets the route class fails here rather than
shipping a race that only shows up as "the UI didn't update".
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from fastapi.routing import APIRoute

from quantvista.api.app import create_app
from quantvista.api.deps import get_tenant_session
from quantvista.api.route_class import CommitBeforeResponseRoute

_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _all_api_routes() -> list[APIRoute]:
    """Every ``APIRoute`` in the app. Included routers are nested, not flattened, so walk them."""
    found: list[APIRoute] = []

    def walk(routes: Iterable[Any] | None) -> None:
        for route in routes or ():
            if isinstance(route, APIRoute):
                found.append(route)
            # `include_router` keeps the router nested (as `_IncludedRouter`) rather than
            # flattening its routes into `app.routes`, so descend through it.
            nested = getattr(route, "original_router", None)
            if nested is not None:
                walk(getattr(nested, "routes", None))

    walk(create_app().routes)
    return found


def _depends_on_tenant_session(route: APIRoute) -> bool:
    """True if the route's unit of work is the RLS tenant session (dependencies can nest)."""

    def walk(dependant: object) -> bool:
        for dep in getattr(dependant, "dependencies", []):
            if dep.call is get_tenant_session or walk(dep):
                return True
        return False

    return walk(route.dependant)


def _tenant_session_routes() -> list[APIRoute]:
    """Routes whose unit of work is the RLS tenant session (the ones the race applies to)."""
    return [r for r in _all_api_routes() if _depends_on_tenant_session(r)]


def test_the_guard_actually_finds_routes() -> None:
    """Guard the guard: a lookup that silently matched nothing would pass everything below."""
    assert len(_tenant_session_routes()) >= 10


def test_every_tenant_write_route_commits_before_responding() -> None:
    offenders = [
        f"{sorted((r.methods or set()) & _WRITE_METHODS)} {r.path}"
        for r in _tenant_session_routes()
        if (r.methods or set()) & _WRITE_METHODS and not isinstance(r, CommitBeforeResponseRoute)
    ]
    assert offenders == [], (
        "these write routes would commit only after the response is sent, so a client that "
        f"re-reads immediately can see stale data: {offenders}"
    )


def test_reads_on_those_routers_are_covered_too() -> None:
    """The route class is applied per-router, so reads share it; it no-ops on safe methods."""
    reads = [r for r in _tenant_session_routes() if not ((r.methods or set()) & _WRITE_METHODS)]
    assert reads and all(isinstance(r, CommitBeforeResponseRoute) for r in reads)
