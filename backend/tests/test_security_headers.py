"""Security response-header tests (QV-079).

DB-free. Asserts every response from the API carries the OWASP-baseline hardening headers
(``SecurityHeadersMiddleware``), that the strict CSP is EXEMPT on the Swagger/ReDoc paths so
they still render, and that HSTS is only emitted when explicitly enabled.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from quantvista.api.app import create_app
from quantvista.api.security_headers import SecurityHeadersMiddleware

_EXPECTED = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "strict-origin-when-cross-origin",
    "permissions-policy": "camera=(), microphone=(), geolocation=()",
    "x-xss-protection": "0",
    "cache-control": "no-store",  # dynamic JSON is never cached (QV-060 stale-read fix)
}


def _client() -> TestClient:
    return TestClient(create_app())


def test_headers_present_on_json_envelope() -> None:
    # /health returns a JSON envelope that RequestContextMiddleware rebuilds — headers must
    # survive that rebuild because SecurityHeadersMiddleware is the OUTERMOST layer.
    r = _client().get("/api/v1/health")
    assert r.status_code == 200
    for key, value in _EXPECTED.items():
        assert r.headers.get(key) == value, key
    assert r.headers.get("content-security-policy") == "default-src 'none'; frame-ancestors 'none'"


def test_headers_present_on_not_found() -> None:
    r = _client().get("/api/v1/does-not-exist")
    assert r.status_code == 404
    for key, value in _EXPECTED.items():
        assert r.headers.get(key) == value, key
    assert "frame-ancestors 'none'" in r.headers.get("content-security-policy", "")


def test_csp_exempt_on_docs_but_other_headers_apply() -> None:
    # Swagger UI loads JS/CSS from a CDN; a blanket default-src 'none' would blank it.
    r = _client().get("/docs")
    assert r.status_code == 200
    assert "content-security-policy" not in {k.lower() for k in r.headers}
    assert r.headers.get("x-content-type-options") == "nosniff"  # non-CSP headers still apply


def test_hsts_absent_by_default_present_when_enabled() -> None:
    # Default settings: hsts_enabled=False → no HSTS header (no TLS in dev/CI).
    r = _client().get("/api/v1/health")
    assert "strict-transport-security" not in {k.lower() for k in r.headers}

    # When enabled, the middleware emits the one-year HSTS directive.
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route

    async def _ok(_request: object) -> PlainTextResponse:
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/", _ok)])
    app.add_middleware(SecurityHeadersMiddleware, hsts_enabled=True)
    r2 = TestClient(app).get("/")
    assert r2.headers.get("strict-transport-security") == "max-age=31536000; includeSubDomains"
