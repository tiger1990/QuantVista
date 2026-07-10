"""News → stock tagging (QV-042) — a pure, precision-first text matcher.

Given the stocks catalog (as ``StockRef`` data — this module imports nothing from ``market_data``,
preserving the ``news ⟂ market_data`` independence contract), decide which single stock an article
is about. **Precision over recall:** tag iff exactly one distinct stock matches; on zero or ≥2
distinct matches, return ``None`` (unmatched / ambiguous — never guess).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from uuid import UUID

# Trailing corporate suffixes stripped to get a company's distinctive "core" name.
_SUFFIXES = frozenset(
    {"ltd", "limited", "inc", "incorporated", "corporation", "corp", "co", "company", "plc"}
)
_MIN_SYMBOL_LEN = 3  # drop noisy 2-char tickers (e.g. "LT") that false-match common words


@dataclass(frozen=True, slots=True)
class StockRef:
    """The match target for one stock (news-side DTO; the job maps the catalog into these)."""

    stock_id: UUID
    symbol: str
    isin: str | None
    company_name: str


def _core_name(name: str) -> str:
    """Lowercase, drop punctuation, strip trailing corporate suffixes, collapse whitespace."""
    tokens = re.sub(r"[^a-z0-9 ]", " ", name.lower()).split()
    while tokens and tokens[-1] in _SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


@dataclass(frozen=True, slots=True)
class MatchIndex:
    """Precomputed aliases → stock_id, plus the raw refs (built once per catalog)."""

    by_core: dict[str, UUID] = field(default_factory=dict)
    by_symbol: dict[str, UUID] = field(default_factory=dict)
    by_isin: dict[str, UUID] = field(default_factory=dict)


def build_match_index(catalog: Sequence[StockRef]) -> MatchIndex:
    """Precompute the alias lookups. A core name shared by ≥2 stocks is dropped (ambiguous)."""
    core_counts: dict[str, int] = {}
    for ref in catalog:
        core = _core_name(ref.company_name)
        if core:
            core_counts[core] = core_counts.get(core, 0) + 1

    index = MatchIndex()
    for ref in catalog:
        core = _core_name(ref.company_name)
        if core and core_counts[core] == 1:  # a non-unique core can never be a confident match
            index.by_core[core] = ref.stock_id
        symbol = ref.symbol.strip().upper()
        if len(symbol) >= _MIN_SYMBOL_LEN:
            index.by_symbol[symbol] = ref.stock_id
        if ref.isin:
            index.by_isin[ref.isin.strip().upper()] = ref.stock_id
    return index


def _normalize(text: str) -> str:
    """Same normalization as ``_core_name`` (minus suffix stripping) so text and cores align."""
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", text.lower()).split())


def match_text(text: str, index: MatchIndex) -> UUID | None:
    """Return the single stock the text is about, or ``None`` (no confident single match)."""
    normalized = _normalize(text)  # punctuation → space (so "Larsen & Toubro" → "larsen toubro")
    matched: set[UUID] = set()

    for core, stock_id in index.by_core.items():
        if re.search(rf"\b{re.escape(core)}\b", normalized):
            matched.add(stock_id)
    for symbol, stock_id in index.by_symbol.items():
        if re.search(rf"\b{re.escape(symbol)}\b", text):  # case-sensitive: tickers are uppercase
            matched.add(stock_id)
    upper = text.upper()
    for isin, stock_id in index.by_isin.items():
        if isin in upper:
            matched.add(stock_id)

    return next(iter(matched)) if len(matched) == 1 else None  # exactly one → tag; else None
