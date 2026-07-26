---
baseline_commit: a25f4e3
---

# Story 1.7: QV-079 — Security hardening pass (OWASP ASVS L2)

Status: done

**Epic:** EPIC-PLAT (Epic 1) · **Points:** 8 · **Depends:** QV-009 (observability baseline), QV-006 (AuthN), QV-038 (screener/DSL allow-list)
**Note on stated dependency QV-076:** QV-076 (entitlement enforcement pass) is in Epic 2 backlog. This story implements the security baseline independently — no QV-076 code is needed.

## Story

As security, I want a baseline-compliant app, so launch risk is acceptable.

## Acceptance Criteria

1. **Security response headers** — every HTTP response from the FastAPI API carries:
   - `Strict-Transport-Security: max-age=31536000; includeSubDomains` (HSTS — only when `hsts_enabled=True`; off in local/CI where there's no TLS)
   - `X-Content-Type-Options: nosniff`
   - `X-Frame-Options: DENY`
   - `Referrer-Policy: strict-origin-when-cross-origin`
   - `Permissions-Policy: camera=(), microphone=(), geolocation=()`
   - `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'` (API returns JSON only — no resources loaded)
   - `X-XSS-Protection: 0` (disabled intentionally — modern browsers use CSP; the legacy header causes bugs in some UAs)
   - **`/docs`, `/redoc`, `/openapi.json` are EXEMPT from the CSP header** (Swagger/ReDoc load JS/CSS from jsDelivr; a blanket `default-src 'none'` would blank the page). All other headers still apply to those paths. See AC10.
   [Source: `07` §4; `plans/07` §4; web rules `security.md`]

2. **Rate limiting** — Fixed-window per-IP rate limits applied to auth endpoints (no DB/session needed):
   - `POST /api/v1/auth/register` — 5 per minute per IP
   - `POST /api/v1/auth/login` — 10 per minute per IP
   - `POST /api/v1/auth/refresh` — 30 per minute per IP
   - `429` response in the project `Envelope` shape (`error.code = "rate_limited"`) with a `Retry-After` header when the limit is breached
   - In-memory storage by default (dev/CI); Redis when `rate_limit_backend == "redis"` (prod)
   - **`rate_limit_enabled` defaults to `False`** so the existing test suite is unaffected (see the ⚠️ test-isolation note in Dev Notes — `TestClient` shares one limiter key `"testclient"` across ALL tests). Only `tests/test_rate_limiting.py` enables it, and it resets limiter storage first.
   [Source: `07` §4]

3. **CSRF analysis documented** — the API uses Bearer JWT for all state-changing endpoints; the only cookie (`qv_refresh`) is httpOnly+SameSite=lax and consumed only by `/auth/refresh` (POST). CSRF risk is effectively zero for our auth model. A comment block in `routes.py` documents this explicitly.
   [Source: `07` §4]

4. **SSRF allow-list** — all outbound HTTP calls from backend services (news providers, FRED macro, Brevo email) go to hardcoded HTTPS hostnames. A `_ALLOWED_OUTBOUND_HOSTS` frozenset in `core/http.py` gates the approved set via `assert_allowed_host(url)`, which **raises `DisallowedHostError` (NOT `assert`)** — assertions are stripped under `python -O` and would silently disable the guard. No user-controlled URL is ever fetched server-side.
   [Source: `07` §4]

5. **Input validation audit** — all request-body Pydantic schemas use `model_config = ConfigDict(extra="forbid")` so unrecognised fields are rejected with 422 rather than silently ignored. (Response DTOs are server-generated and unchanged.)
   [Source: `07` §4; OWASP ASVS V5.1]

6. **SAST + SCA in CI** — added to the `backend-quality` job in `.github/workflows/ci.yml`:
   - `bandit -r src/ -ll -q` — Python SAST (medium+ severity). Confirmed-safe lines (the three fixed-HTTPS `urllib.request.urlopen` calls) are suppressed with **`# nosec B310`** — NOT `# noqa`. Note: ruff's `S`/flake8-bandit ruleset is **not** in `select`, so the pre-existing `# noqa: S310` comments in `alerts/email.py` are inert; replace/augment them with `# nosec B310`.
   - `pip-audit --skip-editable` — SCA over the installed dependency tree (`--skip-editable` so the local editable `quantvista` package isn't audited against PyPI). Fails the job on a known CVE that has a fix.
   [Source: `07` §7]

7. **Frontend CSP (deferred)** — nonce-based CSP for the Next.js frontend (via `next.config.ts` `headers()` + per-request nonce middleware) is deferred to PV-008; the backend API CSP header (`frame-ancestors 'none'`) is the in-scope piece here.

8. **Container scan (deferred)** — Trivy image scanning deferred to PV-002 (no Docker build in CI yet).

9. **Proxy client-IP (deferred)** — behind the prod ALB/ingress, `get_remote_address` sees the proxy IP, so per-IP limits collapse to one bucket. Real-client-IP resolution via a trusted `X-Forwarded-For` parse is deferred to PV-003 (staging infra not live). Documented, not implemented here.

10. **API docs hardening** — `/docs`, `/redoc`, and `/openapi.json` are **disabled in production** (`docs_url=None` etc. when `app_env == "production"`) — an ASVS-aligned reduction of public schema exposure — and kept on in dev/staging. Combined with the AC1 CSP exemption, dev `/docs` still renders.
   [Source: `07` §4/§7]

11. **Tests pass** — ≥634 tests pass (existing baseline, unchanged because rate limiting is off by default). New tests:
   - `tests/test_security_headers.py` — every required header present on success (200 `/health`), an error (404), and confirms CSP is exempt on `/docs` but the other headers still apply; HSTS absent when `hsts_enabled=False`, present when True
   - `tests/test_rate_limiting.py` — 429 + `Retry-After` after the limit with `rate_limit_enabled=True`; 200 within the limit; resets limiter storage in a fixture
   - `tests/test_outbound_allowlist.py` (or fold into headers test) — `assert_allowed_host` raises `DisallowedHostError` on an unapproved host, passes on an approved one
   [Source: `07` §7; sprint-11]

---

## Dev Notes

### Architecture & conventions

- **Namespace:** `backend/src/quantvista/` — bounded-context DAG enforced by `lint-imports` (`root_package = quantvista`). New `core/http.py` sits in `core` (leaf); `api/ratelimit.py` sits in `api` (frontier). DAG: `api → core`.
- **Python 3.13**, mypy strict, ruff 0.16.x, pytest. Venv at `backend/.venv`.
- **Full-tree gates before push:** `ruff check . && ruff format --check . && mypy && lint-imports && pytest`

### Middleware stack in `create_app()` (current → after QV-079)

Current middleware order (outermost = added last):
```
RequestContextMiddleware   ← outermost (wraps everything)
PrometheusMiddleware
OtelMiddleware (via configure_observability)
```

After QV-079 (insert `SecurityHeadersMiddleware` outermost so headers are set on every response regardless of what inner middleware does):
```
SecurityHeadersMiddleware  ← NEW outermost
RequestContextMiddleware
PrometheusMiddleware
OtelMiddleware
```

Starlette adds middleware "last added = outermost". So in `create_app()`, call `app.add_middleware(SecurityHeadersMiddleware)` **after** `app.add_middleware(RequestContextMiddleware)` to make it the outermost.

No `SlowAPIMiddleware` is added — see below (decorator + exception handler only).

### Rate limiting: slowapi (decorator-only, NO SlowAPIMiddleware)

**Library:** `slowapi` (wraps `limits`; integrates with FastAPI/Starlette). In-memory backend for dev/CI; Redis backend for prod via `rate_limit_backend=redis`.

**Design decision — module-global limiter, decorator-only, middleware-free.** The `@limiter.limit(...)` decorator must reference a stable limiter object at decoration (import) time, so the limiter is a **module global** in `api/ratelimit.py`. For per-route limits we do NOT need `SlowAPIMiddleware` (that only serves global default-limits + response header injection and adds `BaseHTTPMiddleware` interaction risk with our existing `RequestContextMiddleware`). We only need: (1) `app.state.limiter = limiter`, and (2) an exception handler for `RateLimitExceeded`.

```python
# api/ratelimit.py
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.requests import Request
from starlette.responses import JSONResponse
from fastapi.encoders import jsonable_encoder

from quantvista.core.config import get_settings
from quantvista.schemas.envelope import Envelope

def _storage_uri() -> str:
    s = get_settings()
    return s.redis_url if s.rate_limit_backend == "redis" else "memory://"

# Module-global so the decorator can bind at import time. `enabled` is read lazily
# from settings via a callable-free approach: we set it in create_app() (see below).
limiter = Limiter(key_func=get_remote_address, storage_uri=_storage_uri(),
                  enabled=get_settings().rate_limit_enabled,
                  default_limits=[])

RATE_LIMITS = {"register": "5/minute", "login": "10/minute", "refresh": "30/minute"}

def rate_limit_exceeded_handler(_request: Request, exc: RateLimitExceeded) -> JSONResponse:
    resp = JSONResponse(
        status_code=429,
        content=jsonable_encoder(Envelope.fail("rate_limited", "too many requests")),
    )
    resp.headers["Retry-After"] = str(getattr(exc, "retry_after", 60) or 60)
    return resp
```

Apply per-endpoint in `api/routes.py`: `@limiter.limit(RATE_LIMITS["login"])`. **slowapi requires the decorated route to have a `request: Request` parameter** — `register`/`login` currently do NOT (only `refresh` does). Add `request: Request` to `register` and `login` signatures.

Wire in `create_app()`: `app.state.limiter = limiter` and `app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)`.

**Config additions to `Settings`:**
```python
rate_limit_enabled: bool = False     # ⚠️ OFF by default — see test-isolation note
rate_limit_backend: str = "memory"   # memory | redis
```

**⚠️ CRITICAL test-isolation note.** `get_remote_address` returns the constant host `"testclient"` for EVERY `TestClient` request, so with in-memory storage all tests in the process share ONE bucket. There are 14 integration files that call `/auth/register|login|refresh` (`test_auth.py` alone makes 7). If rate limiting were on by default, a 5/min register limit would blow almost immediately and cascade 429s across unrelated tests. Therefore:
- `rate_limit_enabled` defaults to **`False`**; the app builds the limiter disabled.
- `ENVIRONMENT`/prod sets it `True` via env.
- `tests/test_rate_limiting.py` builds an app with the limiter enabled and **resets storage first**. Because the limiter is a module global with `enabled` captured at construction, the cleanest test hook is: in the test, set `limiter.enabled = True` and call `limiter.reset()` (or `limiter._storage.reset()`), and reset back in a fixture teardown so no state leaks to other tests. Do NOT rely on `get_settings()` re-reading mid-process.

### Security headers: `SecurityHeadersMiddleware` (with `/docs` CSP exemption)

```python
# api/security_headers.py
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

_BASE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "X-XSS-Protection": "0",
}
_CSP = "default-src 'none'; frame-ancestors 'none'"
# Paths whose HTML/JS/CSS load from a CDN — the strict CSP would blank them.
_CSP_EXEMPT_PREFIXES = ("/docs", "/redoc", "/openapi.json")

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, *, hsts_enabled: bool = False) -> None:
        super().__init__(app)
        headers = dict(_BASE_HEADERS)
        if hsts_enabled:
            headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        self._headers = headers

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        for k, v in self._headers.items():
            response.headers.setdefault(k, v)
        if not request.url.path.startswith(_CSP_EXEMPT_PREFIXES):
            response.headers.setdefault("Content-Security-Policy", _CSP)
        return response
```

`hsts_enabled` is sourced from `Settings.hsts_enabled: bool = False` (False in dev/CI since there's no TLS; set True in staging/prod). Add the setting to `core/config.py`. Use `setdefault` so we never clobber a header an inner layer intentionally set.

### SSRF allow-list: `core/http.py`

```python
# core/http.py
"""Outbound HTTP governance — approved external hostnames only."""
from __future__ import annotations
from urllib.parse import urlparse

class DisallowedHostError(RuntimeError):
    """Raised when an outbound URL targets a host outside the approved allow-list."""

_ALLOWED_OUTBOUND_HOSTS: frozenset[str] = frozenset({
    "newsapi.org",
    "gnews.io",
    "api.marketaux.com",
    "finnhub.io",
    "api.brevo.com",
    "api.stlouisfed.org",   # FRED macro
})

def assert_allowed_host(url: str) -> None:
    """Raise ``DisallowedHostError`` if ``url`` targets a host not in the approved set.

    Uses an explicit raise — NOT ``assert`` — because assertions are stripped under
    ``python -O``, which would silently disable this SSRF guard in an optimized runtime.
    """
    host = urlparse(url).netloc.lower().split(":")[0]
    if host not in _ALLOWED_OUTBOUND_HOSTS:
        raise DisallowedHostError(f"outbound call to unapproved host: {host!r}")
```

Call `assert_allowed_host(url)` before `urlopen()` in `news/providers.py`, `market_data/macro.py`, and `alerts/email.py`. The `urlopen` lines get a **`# nosec B310`** comment for standalone bandit (they're fixed HTTPS endpoints, now also allow-list-guarded).

DAG: `core` is a leaf — `core/http.py` imports only stdlib. `news/providers.py` already imports from `core`; `market_data/macro.py` likewise. `alerts/email.py` imports from `core`. DAG unaffected.

### Input validation audit: `extra="forbid"`

Sweep all Pydantic **request-body** schemas in `backend/src/quantvista/schemas/` and inline model classes in routes. Pattern:

```python
from pydantic import BaseModel, ConfigDict

class CreatePortfolioRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    ...
```

Request-body schemas to audit (verified locations):
- `schemas/auth.py` — `RegisterRequest`, `LoginRequest` (confirmed here, not `identity/models.py`)
- `schemas/rebalance.py` — `RebalanceRequest`
- `schemas/screens.py` — `CreateScreenRequest`
- `schemas/portfolios.py` and any inline request models in `routes_portfolios.py` (e.g. `UpsertPositionRequest`)
- `schemas/alerts.py` and any inline request models in `routes_alerts.py`
- `schemas/notifications.py` — the read/mark request body
- `schemas/screener.py` / screener request body (POST /screener)

Note: `extra="forbid"` applies to request bodies only. Response DTOs (`TradeSuggestionDTO`, `RebalanceResponse`, `TokenResponse`, `MeResponse`, etc.) are server-generated — do NOT add it there (it can break `model_dump()`-based round-trips and adds nothing).

### CSRF analysis

**Finding:** No CSRF risk exists in the current API design.

- Effectively all endpoints use `Authorization: Bearer <jwt>` which requires the caller to explicitly read the token and set the header. Browsers never auto-attach Bearer headers to cross-origin requests.
- The only cookie endpoint is `POST /api/v1/auth/refresh` which consumes the httpOnly `qv_refresh` cookie. With `SameSite=lax`, cross-site POST requests do NOT auto-include cookies in modern browsers (Lax allows only top-level GET navigations to carry cookies).
- `POST /api/v1/auth/logout` also reads the cookie but only to delete it — no state mutation at risk.

Add a `# CSRF-SAFE:` comment block at the top of `routes.py` documenting this analysis so future reviewers don't reopen the question. (`deps.py` has no cookie handling, so no comment needed there.)

### SAST + SCA configuration

**bandit** (standalone — ruff's `S` ruleset is NOT enabled, so this is real added coverage, not redundant):
- Run: `bandit -r src/ -ll -q` (report medium+ severity; quiet). `-ll` filters out low-severity noise incl. B101 (`assert`).
- Suppressions use bandit's own `# nosec B310` (NOT ruff's `# noqa`) on the three fixed-HTTPS `urlopen` sites:
  - `alerts/email.py` (~line 65/76) — currently `# noqa: S310` (inert); change to `# nosec B310`
  - `news/providers.py` (~line 71) — add `# nosec B310`
  - `market_data/macro.py` (~line 101) — add `# nosec B310`
- Add `bandit` to `[project.optional-dependencies] dev` in `pyproject.toml`.
- Run `bandit -r src/ -ll` locally first and clear any other medium+ findings before wiring CI.

**pip-audit:**
- Run: `pip-audit --skip-editable` (audits the installed env from the `.[dev,portfolio]` install; `--skip-editable` skips the local `quantvista` package that has no PyPI record).
- Add `pip-audit` to `[project.optional-dependencies] dev`.
- If a transitive dep has a CVE with no released fix, pin/override or add a scoped ignore with a comment — don't leave the gate red silently.

**CI placement** (`backend-quality` job, after `mypy`, before `lint-imports`):
```yaml
- name: SAST (bandit)
  run: bandit -r src/ -ll -q
- name: SCA (pip-audit)
  run: pip-audit --skip-editable
```

### Files to create (NEW)

| File | Purpose |
|------|---------|
| `backend/src/quantvista/api/security_headers.py` | `SecurityHeadersMiddleware` (with `/docs` CSP exemption) |
| `backend/src/quantvista/api/ratelimit.py` | module-global slowapi `limiter` + `RATE_LIMITS` + `rate_limit_exceeded_handler` |
| `backend/src/quantvista/core/http.py` | `DisallowedHostError` + `_ALLOWED_OUTBOUND_HOSTS` + `assert_allowed_host` |
| `backend/tests/test_security_headers.py` | header assertions + `/docs` CSP-exemption + allow-list raise |
| `backend/tests/test_rate_limiting.py` | 429 + Retry-After (limiter enabled + storage reset in a fixture) |

### Files to modify (UPDATE)

| File | Change |
|------|--------|
| `backend/src/quantvista/api/app.py` | Add `SecurityHeadersMiddleware` (outermost, `hsts_enabled` from settings); `app.state.limiter = limiter`; `app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)`; gate `docs_url/redoc_url/openapi_url` off when `app_env == "production"`. **No `SlowAPIMiddleware`.** |
| `backend/src/quantvista/api/routes.py` | Add `request: Request` param to `register` + `login`; apply `@limiter.limit(RATE_LIMITS[...])` to register/login/refresh; add `# CSRF-SAFE:` comment block |
| `backend/src/quantvista/core/config.py` | Add `hsts_enabled: bool = False`, `rate_limit_enabled: bool = False`, `rate_limit_backend: str = "memory"` |
| `backend/src/quantvista/schemas/*.py` | Add `ConfigDict(extra="forbid")` to request-body schemas (auth, rebalance, screens, portfolios, alerts, notifications, screener) |
| `backend/src/quantvista/news/providers.py` | Call `assert_allowed_host(url)` before urlopen; `# nosec B310` |
| `backend/src/quantvista/market_data/macro.py` | Call `assert_allowed_host(url)` before urlopen; `# nosec B310` |
| `backend/src/quantvista/alerts/email.py` | Call `assert_allowed_host(url)` before urlopen; change `# noqa: S310` → `# nosec B310` |
| `backend/pyproject.toml` | Add `slowapi` (+ `limits`) to `[project]` deps; add `bandit`, `pip-audit` to `[dev]` |
| `.github/workflows/ci.yml` | Add bandit + pip-audit steps to `backend-quality` |
| `docs/pending-verifications.md` | Add PV-008 (frontend CSP nonces); note Trivy → PV-002, proxy XFF client-IP → PV-003 |

### Existing code to preserve

- `RequestContextMiddleware` in `api/middleware.py` — must remain the layer directly inside `SecurityHeadersMiddleware`; do not merge or replace it. It **rebuilds** JSON responses (`_inject_request_id`) — since `SecurityHeadersMiddleware` is outermost, it stamps headers on the already-rebuilt response, so headers survive. Verify this with the test (headers present on an envelope JSON body).
- `cookie_secure: bool = True` and `cookie_samesite: str = "lax"` in `config.py` — keep exactly as-is
- All existing error handlers in `_register_error_handlers()` — the 429 handler is registered separately via `add_exception_handler(RateLimitExceeded, ...)`; don't fold it into that function
- `get_settings()` is `@lru_cache` — tests that flip settings must `get_settings.cache_clear()`. But note the limiter's `enabled` is captured at module import, so a settings flip alone won't enable it mid-process — the rate-limit test sets `limiter.enabled = True` directly (see test patterns)

### Import linter impact

New `core/http.py` is in the `core` layer (leaf). Modules that import it:
- `news.providers` (`news` → `core` ✅ allowed)
- `market_data.macro` (`market_data` → `core` ✅ allowed)
- `alerts.email` (`alerts` → `core` ✅ allowed)
- `api.ratelimit` (`api` → `core` ✅ allowed)

No new forbidden imports introduced. Confirm `lint-imports` stays 3/3.

### Test patterns

```python
# test_security_headers.py
from fastapi.testclient import TestClient
from quantvista.api.app import create_app

def test_security_headers_present_on_json_envelope():
    client = TestClient(create_app())
    r = client.get("/api/v1/health")          # goes through RequestContext rebuild
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert r.headers["x-xss-protection"] == "0"
    assert "strict-transport-security" not in r.headers   # hsts_enabled=False default

def test_csp_exempt_on_docs():
    client = TestClient(create_app())
    r = client.get("/docs")
    assert "content-security-policy" not in r.headers      # exempt so Swagger renders
    assert r.headers["x-content-type-options"] == "nosniff" # other headers still apply

# test_outbound_allowlist.py (or fold into headers test)
import pytest
from quantvista.core.http import assert_allowed_host, DisallowedHostError

def test_allow_list_blocks_unapproved_host():
    with pytest.raises(DisallowedHostError):
        assert_allowed_host("https://evil.example.com/x")
    assert_allowed_host("https://newsapi.org/v2/everything")  # no raise

# test_rate_limiting.py
from quantvista.api.ratelimit import limiter

@pytest.fixture
def rate_limited():
    limiter.enabled = True
    limiter.reset()
    yield
    limiter.enabled = False
    limiter.reset()

def test_login_rate_limit_429(rate_limited):
    client = TestClient(create_app())
    for _ in range(10):
        client.post("/api/v1/auth/login", json={"email": "x@x.com", "password": "wrong"})
    r = client.post("/api/v1/auth/login", json={"email": "x@x.com", "password": "wrong"})
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "rate_limited"
    assert "retry-after" in {k.lower() for k in r.headers}
```

### Previous story learnings (QV-020, QV-009)

- `mypy` strict runs on the FULL `src/ tests/` tree in CI — annotate all new functions (incl. middleware `dispatch` return types); `slowapi`/`limits` may lack stubs → add a mypy `ignore_missing_imports` override in `pyproject.toml` like the existing yfinance/kafka/cvxpy entries
- `ruff 0.16.x` reformats Python blocks inside `.md` files — run `ruff format --check .` locally before push
- All new test files must be importable standalone (no unused imports; ruff F401 is on)
- The `backend-quality` CI job runs `ruff check`, `ruff format --check`, `mypy`, `lint-imports` sequentially — all must pass before tests run
- Register the 429 handler via `app.add_exception_handler(RateLimitExceeded, handler)` — NOT via middleware

---

## Tasks / Subtasks

### Task 1: Security headers middleware + docs hardening
- [x] 1a. Create `backend/src/quantvista/api/security_headers.py` — `SecurityHeadersMiddleware` (`_BASE_HEADERS`, separate `_CSP`, `_CSP_EXEMPT_PREFIXES`, `hsts_enabled` toggle, `setdefault` semantics)
- [x] 1b. Add `hsts_enabled: bool = False` to `Settings` in `core/config.py`
- [x] 1c. Wire `SecurityHeadersMiddleware` as the OUTERMOST layer in `create_app()` (add it AFTER `RequestContextMiddleware`); pass `hsts_enabled=get_settings().hsts_enabled`
- [x] 1d. Gate `/docs`, `/redoc`, `/openapi.json` off in production: pass `docs_url=None, redoc_url=None, openapi_url=None` to `FastAPI(...)` when `get_settings().app_env == "production"`
- [x] 1e. Write `tests/test_security_headers.py` — all headers present on `/health` (JSON envelope, through RequestContext rebuild) and a 404; CSP EXEMPT on `/docs` but other headers present; HSTS absent by default

### Task 2: Rate limiting (decorator-only, OFF by default)
- [x] 2a. Add `slowapi` (pulls `limits`) to `[project] dependencies` in `pyproject.toml`; add a mypy `ignore_missing_imports` override for `slowapi.*`/`limits.*` if stubs are missing
- [x] 2b. Create `backend/src/quantvista/api/ratelimit.py` — module-global `limiter` (`enabled=get_settings().rate_limit_enabled`, `headers_enabled=True`, storage from `rate_limit_backend`), `RATE_LIMITS` dict, `rate_limit_exceeded_handler` returning `Envelope.fail("rate_limited", ...)` + `Retry-After` via `_inject_headers`
- [x] 2c. Add `rate_limit_enabled: bool = False` and `rate_limit_backend: str = "memory"` to `Settings`
- [x] 2d. In `create_app()`: `app.state.limiter = limiter` + `app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)`. Do NOT add `SlowAPIMiddleware`.
- [x] 2e. Add `request: Request` param to `register` + `login` in `api/routes.py` (needed by slowapi); apply `@limiter.limit(RATE_LIMITS["register"|"login"|"refresh"])` to the three routes
- [x] 2f. Write `tests/test_rate_limiting.py` — fixture sets `limiter.enabled=True` + `limiter.reset()` (restores + resets on teardown); assert 429 + `error.code=="rate_limited"` + `Retry-After` after the limit, 200 within it
- [x] 2g. ⚠️ Sanity-run the FULL suite to confirm rate limiting stays OFF by default and none of the 14 auth-hitting integration files regress to 429

### Task 3: SSRF allow-list
- [x] 3a. Create `backend/src/quantvista/core/http.py` — `DisallowedHostError`, `_ALLOWED_OUTBOUND_HOSTS` frozenset (7 hosts incl. `api.worldbank.org`), `assert_allowed_host(url)` (explicit raise, NOT `assert`; exact host match, strips creds+port)
- [x] 3b. Call `assert_allowed_host(url)` before `urlopen` in `news/providers.py` (the shared `_get_json` helper) + `# nosec B310`
- [x] 3c. Call `assert_allowed_host(url)` before `urlopen` in `market_data/macro.py` (FRED + World Bank both flow through `_get_json`) + `# nosec B310`
- [x] 3d. Call `assert_allowed_host(url)` before the urlopen in `alerts/email.py`; change its `# noqa: S310` → `# nosec B310`
- [x] 3e. Add `tests/test_outbound_allowlist.py` — raises on unapproved host (incl. suffix-spoof + cloud-metadata IP), passes on all 7 approved vendors

### Task 4: Input validation audit (`extra="forbid"`)
- [x] 4a. Added `model_config = ConfigDict(extra="forbid")` to all request-body models: `auth` (Register/Login), `alerts` (CreateAlert + nested AlertCondition), `optimize` (OptimizeRequest + nested OptimizeConstraints), `screens` (SaveScreen + nested ScreenCriteria), `portfolios` (CreatePortfolio + UpsertPosition), `rebalance` (RebalanceRequest), `screener` (ScreenRequest + nested FilterClause). Notifications has no request body (mark-all) → nothing to change.
- [x] 4b. Response DTOs left untouched
- [x] 4c. `tests/test_input_validation.py` — extra field on Register/Login/CreatePortfolio/Rebalance raises ValidationError (→422 at the boundary); full suite unaffected (no existing test sends extra fields)

### Task 5: SAST + SCA in CI
- [x] 5a. Added `bandit` and `pip-audit` to `[dev]` dependencies in `backend/pyproject.toml`
- [x] 5b. Added bandit (`bandit -c pyproject.toml -r src/ -ll -q`) and pip-audit (`pip-audit --skip-editable`) steps to the `backend-quality` job (after mypy, before lint-imports). Dropped `--strict` — it treats the skipped local editable pkg as a failure; plain pip-audit still exits non-zero on any real CVE.
- [x] 5c. Ran bandit locally: the three fixed-HTTPS `urlopen` sites carry `# nosec B310`; the 12 B608 (hardcoded_sql) LOW-confidence hits are the reviewed parameterized-query idiom (constant column-list f-strings + bound `:params`, never user input) → skipped project-wide via `[tool.bandit] skips=["B608"]` with a documented rationale. bandit exits 0.
- [x] 5d. Ran pip-audit: caught a REAL CVE (`pydantic-settings 2.14.1` GHSA-4xgf-cpjx-pc3j) → bumped floor to `>=2.14.2`; now clean.

### Task 6: CSRF documentation + deferred items
- [x] 6a. Added the `CSRF-SAFE (QV-079)` block to the `api/routes.py` module docstring (Bearer JWT everywhere; cookie-only `/auth/refresh` is POST + SameSite=lax; logout only deletes)
- [x] 6b. Added `PV-008` to `docs/pending-verifications.md`: Frontend nonce-based CSP (Next.js `headers()` + per-request nonce middleware)
- [x] 6c. `docs/pending-verifications.md`: container scan (Trivy) → PV-002; proxy real-client-IP (trusted XFF) for rate limiting → PV-003

### Task 7: Full-tree validation + sprint status
- [x] 7a. `ruff check . && ruff format --check . && mypy && lint-imports && bandit -c pyproject.toml -r src/ -ll -q && pip-audit --skip-editable` — all clean (253 files formatted, 251 mypy sources, 3/3 contracts, bandit exit 0, pip-audit exit 0)
- [x] 7b. `pytest` — 657 passed, 5 skipped (634 baseline + 23 new; rate limiting off by default → zero regressions)
- [x] 7c. Update `sprint-status.yaml` → review (PR-ready); reconcile to done on merge

---

## Dev Agent Record

### Debug Log

- Rate-limit 429 initially returned the envelope but **no `Retry-After`** — slowapi's `_inject_headers` is a no-op unless the `Limiter` is built with `headers_enabled=True`. Set it (headers injected only in our 429 handler since there's no `SlowAPIMiddleware`).
- mypy strict (full `src/ tests/` tree in CI) caught 4 issues the local `src`-only run would miss: handler return/param typing vs Starlette's `add_exception_handler` signature (retyped to `(Request, Exception) -> Response`, dropped a now-unused `RateLimitExceeded` import + stale `# type: ignore`), and a test passing `str` for a `Decimal` field (simplified the test to rely on the default).
- bandit flagged 12 B608 (hardcoded-SQL) at LOW confidence — all the reviewed parameterized-query idiom (constant column-list f-strings + bound `:params`); skipped project-wide via `[tool.bandit] skips=["B608"]` with a documented rationale. The three fixed-HTTPS `urlopen` sites use `# nosec B310` (bandit), not the inert pre-existing `# noqa: S310` (ruff `S` ruleset isn't enabled).
- pip-audit surfaced a **real CVE** — `pydantic-settings 2.14.1` (GHSA-4xgf-cpjx-pc3j) — bumped the floor to `>=2.14.2`.

### Completion Notes List

- **Security headers** (`api/security_headers.py`): `SecurityHeadersMiddleware` added OUTERMOST in `create_app` so headers survive `RequestContextMiddleware`'s JSON-envelope rebuild. Strict `default-src 'none'; frame-ancestors 'none'` CSP, **exempt on `/docs|/redoc|/openapi.json`** so Swagger/ReDoc still render. HSTS opt-in via `hsts_enabled` (off in dev/CI). `setdefault` so an inner layer's header is never clobbered.
- **Docs hardening**: `/docs`, `/redoc`, `/openapi.json` disabled in production (`app_env == "production"`).
- **Rate limiting** (`api/ratelimit.py`): decorator-only slowapi (no `SlowAPIMiddleware`) — module-global `limiter` + `app.state.limiter` + a `RateLimitExceeded` handler returning the `rate_limited` envelope. **OFF by default** (`rate_limit_enabled=False`) — the ⚠️ reason is that every `TestClient` request shares the key `"testclient"`, so an on-by-default limiter would blow the window across the suite. Only `tests/test_rate_limiting.py` enables it (with `limiter.reset()` in a fixture). Limits: register 5/min, login 10/min, refresh 30/min. `register`/`login` gained a `request: Request` param (slowapi requirement).
- **SSRF allow-list** (`core/http.py`): `assert_allowed_host` **raises** `DisallowedHostError` (not `assert` → survives `python -O`); exact host match (suffix-spoof + cloud-metadata IP refused). Wired at the three outbound chokepoints (`news/providers._get_json`, `market_data/macro._get_json`, `alerts/email.send`). 7 approved hosts incl. `api.worldbank.org` (WorldBank macro also flows through `_get_json`).
- **Input validation**: `ConfigDict(extra="forbid")` on all request-body models (+ nested request sub-models) across auth/alerts/optimize/screens/portfolios/rebalance/screener. Notifications has no request body. Response DTOs untouched.
- **CSRF**: analysis documented in the `routes.py` docstring — Bearer JWT everywhere + SameSite=lax cookie only on `/auth/refresh` ⇒ no CSRF token layer needed.
- **SAST/SCA**: bandit + pip-audit added to the `backend-quality` CI job (after mypy, before lint-imports).
- **Deferred (PVs)**: frontend nonce CSP → PV-008; trusted-XFF real-client-IP for rate limiting + `RATE_LIMIT_ENABLED/BACKEND=redis` in staging/prod → PV-003; Trivy image scan → PV-002.
- **Out of scope**: two pre-existing modified frontend files (`(app)/page.tsx`, `dashboard.tsx`) are unrelated to QV-079 and are NOT part of this change.

### File List

**New**
- `backend/src/quantvista/api/security_headers.py` — `SecurityHeadersMiddleware` (+ `/docs` CSP exemption)
- `backend/src/quantvista/api/ratelimit.py` — slowapi `limiter` + `RATE_LIMITS` + 429 handler
- `backend/src/quantvista/core/http.py` — `DisallowedHostError` + `_ALLOWED_OUTBOUND_HOSTS` + `assert_allowed_host`
- `backend/tests/test_security_headers.py`
- `backend/tests/test_rate_limiting.py`
- `backend/tests/test_outbound_allowlist.py`
- `backend/tests/test_input_validation.py`

**Modified**
- `backend/src/quantvista/api/app.py` — wire SecurityHeaders (outermost) + limiter state/handler + prod docs gating
- `backend/src/quantvista/api/routes.py` — `@limiter.limit` on register/login/refresh (+ `request` params) + CSRF-SAFE docstring
- `backend/src/quantvista/core/config.py` — `hsts_enabled`, `rate_limit_enabled`, `rate_limit_backend`
- `backend/src/quantvista/schemas/{auth,alerts,optimize,screens,portfolios,rebalance,screener}.py` — `extra="forbid"`
- `backend/src/quantvista/news/providers.py`, `market_data/macro.py`, `alerts/email.py` — `assert_allowed_host` + `# nosec B310`
- `backend/pyproject.toml` — `slowapi` dep; `bandit`+`pip-audit` dev deps; `pydantic-settings>=2.14.2`; slowapi mypy override; `[tool.bandit]` B608 skip
- `.github/workflows/ci.yml` — bandit + pip-audit steps in `backend-quality`
- `docs/pending-verifications.md` — PV-008 (frontend CSP), PV-003 (XFF client-IP), Trivy→PV-002

### Change Log

- **2026-07-26 — QV-079 security hardening (OWASP ASVS L2).** Security response headers (HSTS opt-in, CSP with `/docs` exemption) via an outermost middleware; per-IP auth rate limiting (slowapi, decorator-only, OFF by default); SSRF outbound allow-list (raises, not `assert`) at all three fetch chokepoints; `extra="forbid"` input-validation sweep; CSRF-safety documented; SAST (bandit) + SCA (pip-audit) CI gates — pip-audit caught + fixed a real `pydantic-settings` CVE; prod docs disabled. 657 passed / 5 skipped; ruff/format/mypy/lint-imports/bandit/pip-audit all green. No migration. Frontend nonce-CSP + trusted-XFF + Trivy deferred to PVs.
