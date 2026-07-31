"""Commit the request's unit of work *before* the response is sent.

FastAPI finalises ``yield`` dependencies **after** the response has gone out (since 0.106), and
``get_tenant_session`` commits in exactly that exit code (``core.db.session_scope``). A client that
mutates and immediately re-reads therefore races the commit and can observe pre-commit state — a
deleted row still listed, or a freshly created row 404ing on the poll that follows its own 201/202.

A custom ``APIRoute`` closes that window with well-defined ordering: Starlette's
``request_response`` awaits the route handler to obtain the ``Response`` and only then sends it, so
anything the handler does happens strictly before the client can see the result. Committing here —
rather than in each endpoint — means new write routes inherit the guarantee automatically.

If the endpoint raises, the commit is skipped and ``session_scope`` rolls back, as before.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Request, Response
from fastapi.routing import APIRoute

#: Where ``deps.get_tenant_session`` parks the session for this request.
SESSION_STATE_ATTR = "db_session"

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class CommitBeforeResponseRoute(APIRoute):
    """An ``APIRoute`` that commits the request-scoped session before the response is sent."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            response = await original(request)
            if request.method in _SAFE_METHODS:
                return response  # a read has nothing to publish; leave its transaction alone
            session = getattr(request.state, SESSION_STATE_ATTR, None)
            # `in_transaction()` makes this a no-op when the endpoint already committed (submit
            # does, because it must publish its job only after the row exists).
            if session is not None and session.in_transaction():
                session.commit()
            return response

        return handler


__all__ = ["SESSION_STATE_ATTR", "CommitBeforeResponseRoute"]
