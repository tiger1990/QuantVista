"""Outbound-host allow-list tests (QV-079 SSRF guard).

``assert_allowed_host`` must RAISE (not ``assert``) on any host outside the approved set — the
raise survives ``python -O`` where a bare ``assert`` would be stripped, silently disabling the
guard. Every real vendor host the backend calls must be present in the allow-list.
"""

from __future__ import annotations

import pytest

from quantvista.core.http import (
    _ALLOWED_OUTBOUND_HOSTS,
    DisallowedHostError,
    assert_allowed_host,
)


@pytest.mark.parametrize(
    "url",
    [
        "https://newsapi.org/v2/everything?q=x",
        "https://gnews.io/api/v4/search",
        "https://api.marketaux.com/v1/news/all",
        "https://finnhub.io/api/v1/news",
        "https://api.brevo.com/v3/smtp/email",
        "https://api.stlouisfed.org/fred/series/observations",
    ],
)
def test_approved_hosts_pass(url: str) -> None:
    assert_allowed_host(url)  # must not raise


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example.com/steal",
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata SSRF classic
        "https://newsapi.org.evil.com/x",  # suffix-spoof must NOT match
        "https://localhost:8000/internal",
    ],
)
def test_unapproved_hosts_raise(url: str) -> None:
    with pytest.raises(DisallowedHostError):
        assert_allowed_host(url)


def test_every_real_vendor_host_is_listed() -> None:
    # The four news providers + Brevo + FRED + World Bank — every host fetched server-side.
    for host in (
        "newsapi.org",
        "gnews.io",
        "api.marketaux.com",
        "finnhub.io",
        "api.brevo.com",
        "api.stlouisfed.org",
        "api.worldbank.org",
    ):
        assert host in _ALLOWED_OUTBOUND_HOSTS
