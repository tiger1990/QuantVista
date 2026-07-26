"""Outbound HTTP governance (QV-079) — approved external hostnames only.

Every server-side fetch (news providers, FRED/World Bank macro, Brevo email) targets a fixed,
hardcoded HTTPS vendor endpoint. ``assert_allowed_host`` is called at each outbound chokepoint as
a defense-in-depth SSRF guard: even if a URL ever became partly data-derived, a host outside the
approved set is refused.

It RAISES ``DisallowedHostError`` rather than using ``assert`` — a bare ``assert`` is stripped
under ``python -O``, which would silently disable the guard in an optimized runtime.
"""

from __future__ import annotations

from urllib.parse import urlparse


class DisallowedHostError(RuntimeError):
    """Raised when an outbound URL targets a host outside the approved allow-list."""


# The ONLY hosts the backend fetches server-side. Add a host here (with review) when a new
# vendor adapter is introduced — never fetch a user-controlled URL.
_ALLOWED_OUTBOUND_HOSTS: frozenset[str] = frozenset(
    {
        "newsapi.org",  # NewsAPI.org (QV-041)
        "gnews.io",  # GNews (QV-041)
        "api.marketaux.com",  # Marketaux (QV-041)
        "finnhub.io",  # Finnhub (QV-041)
        "api.brevo.com",  # Brevo transactional email (QV-049)
        "api.stlouisfed.org",  # FRED macro (QV-026)
        "api.worldbank.org",  # World Bank macro (QV-026)
    }
)


def assert_allowed_host(url: str) -> None:
    """Raise ``DisallowedHostError`` if ``url``'s host is not in the approved allow-list.

    Exact host match (no suffix logic), so ``newsapi.org.evil.com`` is refused. Any port is
    stripped before comparison.
    """
    host = urlparse(url).netloc.lower().rsplit("@", 1)[-1].split(":")[0]
    if host not in _ALLOWED_OUTBOUND_HOSTS:
        raise DisallowedHostError(f"outbound call to unapproved host: {host!r}")


__all__ = ["DisallowedHostError", "assert_allowed_host"]
