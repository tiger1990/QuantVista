"""Structured logging via structlog (JSON in cloud, console locally).

Every record is correlated (``request_id``/``trace_id``/``span_id`` from
``structlog.contextvars``) and carries the runtime ``role``. A PII-aware redaction
processor masks secrets/credentials before rendering — a compliance requirement
(``plans/07``), not a convenience: passwords, tokens, cookies, and JWTs must never be
logged. Configure once per process at startup for both the api and worker roles.

Redaction — what is and isn't covered (read before logging sensitive data):
- Structured fields (keyword args) are masked by key name: an exact denylist plus a
  substring scan (``token``/``secret``/``password``/…). Nested dicts are walked to a
  bounded depth so ``log.info("req", headers={"authorization": ...})`` is still masked.
- Rendered exception/stack strings (``exc_info``/``stack``) are regex-scrubbed for
  ``key=value`` credential pairs, bearer tokens, and URL user:pass credentials.
- **LIMITATION:** the free-text log *message* is NOT scanned. Never interpolate a secret
  into the message — ``log.info("issuing token", token=t)`` (redacted), never
  ``log.info(f"issuing token {t}")`` (leaks). Pass secrets as keyword args, not f-strings.
"""

from __future__ import annotations

import re
from typing import Any

import structlog
from structlog.typing import EventDict, Processor, WrappedLogger

from quantvista.core.config import get_settings

# Exact key names (normalised: lowercased, hyphens→underscores) that are always secrets.
SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "authorization",
        "jwt",
        "refresh",
        "session",
        "session_id",
        "sid",
        "otp",
        "totp",
        "auth",
    }
)

# Substrings that mark a key as sensitive wherever they appear (so future variants like
# ``new_password``/``x_access_token`` are caught). Deliberately excludes a bare ``key`` so
# legitimate diagnostic fields (``run_key``, ``cache_key``, ``idempotency_key``) survive.
_SENSITIVE_SUBSTRINGS: tuple[str, ...] = (
    "password",
    "passwd",
    "secret",
    "token",
    "credential",
    "authorization",
    "cookie",
    "api_key",
    "apikey",
    "private_key",
    "access_key",
)

_REDACTED = "***redacted***"
_MAX_REDACT_DEPTH = 3

# Scrub patterns for already-rendered exception/stack strings (H-1): key=value credential
# pairs, bearer tokens, and URL ``scheme://user:pass@host`` credentials.
_EXC_SCRUB: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"(?i)(password|passwd|secret|token|credential|api[_-]?key|authorization|bearer)"
            r"(['\"]?\s*[=:]\s*['\"]?)[^\s,'\"}&]+"
        ),
        r"\1\2***redacted***",
    ),
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]+"), "Bearer ***redacted***"),
    (re.compile(r"://([^:/@\s]+):[^@/\s]+@"), r"://\1:***redacted***@"),
)


def _mask_email(value: str) -> str:
    """Mask the local part of an email, keeping the domain for debugging."""
    local, sep, domain = value.partition("@")
    if not sep or not local:
        return value
    return f"{local[0]}***@{domain}"


def _is_sensitive_key(key: str) -> bool:
    norm = key.lower().replace("-", "_")
    return norm in SENSITIVE_KEYS or any(sub in norm for sub in _SENSITIVE_SUBSTRINGS)


def _redact_value(key: str, value: Any, depth: int) -> Any:
    if _is_sensitive_key(key):
        return _REDACTED
    if isinstance(value, dict) and depth > 0:
        return {k: _redact_value(k, v, depth - 1) for k, v in value.items()}
    if key.lower() == "email" and isinstance(value, str):
        return _mask_email(value)
    return value


def redact_pii(_logger: WrappedLogger, _method_name: str, event_dict: EventDict) -> EventDict:
    """structlog processor: mask sensitive values by key name, walking nested dicts."""
    for key, value in list(event_dict.items()):
        event_dict[key] = _redact_value(key, value, _MAX_REDACT_DEPTH)
    return event_dict


def sanitize_exc_info(
    _logger: WrappedLogger, _method_name: str, event_dict: EventDict
) -> EventDict:
    """Scrub credentials from already-rendered ``exc_info``/``stack`` strings (H-1)."""
    for field in ("exc_info", "stack"):
        text = event_dict.get(field)
        if isinstance(text, str):
            for pattern, repl in _EXC_SCRUB:
                text = pattern.sub(repl, text)
            event_dict[field] = text
    return event_dict


def _add_role(role: str) -> Processor:
    def processor(_logger: WrappedLogger, _method_name: str, event_dict: EventDict) -> EventDict:
        event_dict["role"] = role
        return event_dict

    return processor


def configure_logging(role: str) -> None:
    """Install the structlog pipeline for ``role`` (idempotent per process)."""
    settings = get_settings()
    renderer: Any = (
        structlog.processors.JSONRenderer()
        if settings.log_json
        else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            _add_role(role),
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            sanitize_exc_info,
            redact_pii,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(_level_to_number(settings.log_level)),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def _level_to_number(level: str) -> int:
    import logging

    return getattr(logging, level.upper(), logging.INFO)
