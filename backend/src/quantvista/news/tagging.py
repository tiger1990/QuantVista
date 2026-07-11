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
# Trailing descriptor/stop words dropped to derive a SHORT alias (news often omits them, e.g.
# "Kalyan Jewellers India Ltd" → "kalyan jewellers"). Only stripped from the tail.
_SHORT_TAIL = _SUFFIXES | {"india", "of", "the", "and"}
_MIN_SYMBOL_LEN = 3  # drop noisy 2-char tickers (e.g. "LT") that false-match common words
_MIN_SHORT_TOKENS = 2  # a short alias must stay ≥2 tokens ("kalyan jewellers" ok; "bank" not)


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


def _name_aliases(name: str) -> set[str]:
    """The name phrases to match a stock by: the full core + a short alias (trailing India/stop
    words stripped) when it stays ≥2 tokens — so "Kalyan Jewellers India Ltd" also matches the
    bare "Kalyan Jewellers", while "Bank of India" never degrades to the unsafe "bank"."""
    core = _core_name(name)
    if not core:
        return set()
    aliases = {core}
    tokens = core.split()
    while tokens and tokens[-1] in _SHORT_TAIL:
        tokens.pop()
    if len(tokens) >= _MIN_SHORT_TOKENS:
        aliases.add(" ".join(tokens))
    return aliases


@dataclass(frozen=True, slots=True)
class MatchIndex:
    """Precomputed aliases → stock_id, plus the raw refs (built once per catalog)."""

    by_core: dict[str, UUID] = field(default_factory=dict)
    by_symbol: dict[str, UUID] = field(default_factory=dict)
    by_isin: dict[str, UUID] = field(default_factory=dict)


def build_match_index(catalog: Sequence[StockRef]) -> MatchIndex:
    """Precompute the alias lookups. A name alias shared by ≥2 stocks is dropped (ambiguous)."""
    alias_counts: dict[str, int] = {}
    for ref in catalog:
        for alias in _name_aliases(ref.company_name):
            alias_counts[alias] = alias_counts.get(alias, 0) + 1

    index = MatchIndex()
    for ref in catalog:
        for alias in _name_aliases(ref.company_name):
            if alias_counts[alias] == 1:  # a non-unique alias can never be a confident match
                index.by_core[alias] = ref.stock_id
        symbol = ref.symbol.strip().upper()
        if len(symbol) >= _MIN_SYMBOL_LEN:
            index.by_symbol[symbol] = ref.stock_id
        if ref.isin:
            index.by_isin[ref.isin.strip().upper()] = ref.stock_id
    return index


def _normalize(text: str) -> str:
    """Same normalization as ``_core_name`` (minus suffix stripping) so text and cores align."""
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", text.lower()).split())


def match_all(text: str, index: MatchIndex) -> set[UUID]:
    """Every distinct stock the text confidently names (QV-094 — a multi-stock article tags all).

    Per-match precision is unchanged from the single-match matcher (whole normalized company-name
    phrase, symbol ≥3 chars, ISIN; catalog cores shared by ≥2 stocks are excluded at index build).
    """
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

    return matched
