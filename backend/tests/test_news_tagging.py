"""Unit tests for the pure news→stock matcher (news.tagging, QV-042).

Precision-over-recall: exact single match tags; ambiguous or none → None. Suffix normalization,
short-symbol rejection, and non-unique core names are pinned here.
"""

from __future__ import annotations

from uuid import uuid4

from quantvista.news.tagging import StockRef, build_match_index, match_text

RELIANCE = StockRef(uuid4(), "RELIANCE", "INE002A01018", "Reliance Industries Ltd")
TCS = StockRef(uuid4(), "TCS", "INE467B01029", "Tata Consultancy Services Ltd")
INFY = StockRef(uuid4(), "INFY", "INE009A01021", "Infosys Ltd")
LT = StockRef(uuid4(), "LT", "INE018A01030", "Larsen & Toubro Ltd")  # 2-char symbol
CATALOG = [RELIANCE, TCS, INFY, LT]
INDEX = build_match_index(CATALOG)


def test_matches_company_name_phrase() -> None:
    assert match_text("Reliance Industries posts record profit", INDEX) == RELIANCE.stock_id


def test_normalizes_corporate_suffix() -> None:
    # "Ltd" is stripped from the catalog core, so the bare name still matches.
    assert match_text("Tata Consultancy Services wins deal", INDEX) == TCS.stock_id


def test_matches_symbol_word_bounded() -> None:
    assert match_text("INFY up 3% on strong guidance", INDEX) == INFY.stock_id


def test_matches_isin() -> None:
    assert match_text("Corporate action for INE009A01021 announced", INDEX) == INFY.stock_id


def test_two_char_symbol_is_not_matched() -> None:
    # "LT" as a bare token must NOT tag Larsen & Toubro (too noisy); its full name still can.
    assert match_text("The report was LT rated overall", INDEX) is None
    assert match_text("Larsen & Toubro bags order", INDEX) == LT.stock_id


def test_ambiguous_multiple_stocks_returns_none() -> None:
    assert match_text("Reliance Industries and Infosys both rallied", INDEX) is None


def test_no_match_returns_none() -> None:
    assert match_text("Global markets mixed amid rate worries", INDEX) is None


def test_non_unique_core_name_never_matches() -> None:
    a = StockRef(uuid4(), "ABCA", None, "Aditya Birla Capital Ltd")
    b = StockRef(uuid4(), "ABCB", None, "Aditya Birla Capital Ltd")  # same core → ambiguous
    idx = build_match_index([a, b])
    assert match_text("Aditya Birla Capital raises funds", idx) is None


def test_substring_does_not_false_match() -> None:
    # "Infosys" must not match inside an unrelated longer word.
    assert match_text("Reinfosysation is not a company", INDEX) is None
