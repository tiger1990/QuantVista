"""Unit tests for the request-context middleware (api.middleware)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from quantvista.api.middleware import REQUEST_ID_HEADER, RequestContextMiddleware
from quantvista.schemas.envelope import Envelope


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    @app.get("/ok")
    def ok() -> Envelope[dict[str, str]]:
        return Envelope.ok({"hello": "world"}, meta={"next_cursor": "abc"})

    @app.get("/boom")
    def boom() -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content=jsonable_encoder(Envelope.fail("conflict", "nope")),
        )

    return app


def test_generates_and_echoes_request_id() -> None:
    # Arrange
    client = TestClient(_app())
    # Act
    resp = client.get("/ok")
    # Assert — header present and mirrored in the envelope meta
    header_id = resp.headers[REQUEST_ID_HEADER]
    assert header_id
    assert resp.json()["meta"]["request_id"] == header_id


def test_honors_inbound_request_id() -> None:
    # Arrange
    client = TestClient(_app())
    # Act
    resp = client.get("/ok", headers={REQUEST_ID_HEADER: "caller-123"})
    # Assert
    assert resp.headers[REQUEST_ID_HEADER] == "caller-123"
    assert resp.json()["meta"]["request_id"] == "caller-123"


def test_rejects_unsafe_inbound_request_id() -> None:
    # Arrange — a log-injection payload (newline + crafted fields), oversized
    client = TestClient(_app())
    evil = "ok\nlevel=critical event=FAKE"
    # Act
    resp = client.get("/ok", headers={REQUEST_ID_HEADER: evil})
    # Assert — the unsafe value is discarded for a server-generated safe id
    served = resp.headers[REQUEST_ID_HEADER]
    assert served != evil
    assert "\n" not in served
    assert resp.json()["meta"]["request_id"] == served


def test_rejects_overlong_request_id() -> None:
    # Arrange
    client = TestClient(_app())
    # Act
    resp = client.get("/ok", headers={REQUEST_ID_HEADER: "a" * 500})
    # Assert — capped: the 500-char value is not echoed back
    assert resp.headers[REQUEST_ID_HEADER] != "a" * 500
    assert len(resp.headers[REQUEST_ID_HEADER]) <= 128


def test_preserves_existing_meta() -> None:
    # Arrange
    client = TestClient(_app())
    # Act
    body = client.get("/ok").json()
    # Assert — request_id added without dropping next_cursor
    assert body["meta"]["next_cursor"] == "abc"
    assert "request_id" in body["meta"]


def test_error_envelope_shape_unchanged() -> None:
    # Arrange
    client = TestClient(_app())
    # Act
    resp = client.get("/boom")
    body = resp.json()
    # Assert — header still set, but error payload is untouched (no meta injection)
    assert resp.headers[REQUEST_ID_HEADER]
    assert resp.status_code == 409
    assert body["success"] is False
    assert body["error"] == {"code": "conflict", "message": "nope"}
