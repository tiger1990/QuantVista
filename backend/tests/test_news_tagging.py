"""Unit tests for the pure news→stock matcher (news.tagging, QV-042 / QV-094).

``match_all`` returns *every* confident distinct match (a multi-stock article tags all). Per-match
precision is unchanged: suffix normalization, short-symbol rejection, non-unique core names, and the
substring guard are pinned here.
"""

from __future__ import annotations

from uuid import uuid4

from quantvista.news.tagging import StockRef, build_match_index, match_all

RELIANCE = StockRef(uuid4(), "RELIANCE", "INE002A01018", "Reliance Industries Ltd")
TCS = StockRef(uuid4(), "TCS", "INE467B01029", "Tata Consultancy Services Ltd")
INFY = StockRef(uuid4(), "INFY", "INE009A01021", "Infosys Ltd")
LT = StockRef(uuid4(), "LT", "INE018A01030", "Larsen & Toubro Ltd")  # 2-char symbol
CATALOG = [RELIANCE, TCS, INFY, LT]
INDEX = build_match_index(CATALOG)


def test_matches_company_name_phrase() -> None:
    assert match_all("Reliance Industries posts record profit", INDEX) == {RELIANCE.stock_id}


def test_normalizes_corporate_suffix() -> None:
    # "Ltd" is stripped from the catalog core, so the bare name still matches.
    assert match_all("Tata Consultancy Services wins deal", INDEX) == {TCS.stock_id}


def test_matches_symbol_word_bounded() -> None:
    assert match_all("INFY up 3% on strong guidance", INDEX) == {INFY.stock_id}


def test_matches_isin() -> None:
    assert match_all("Corporate action for INE009A01021 announced", INDEX) == {INFY.stock_id}


def test_two_char_symbol_is_not_matched() -> None:
    # "LT" as a bare token must NOT tag Larsen & Toubro (too noisy); its full name still can.
    assert match_all("The report was LT rated overall", INDEX) == set()
    assert match_all("Larsen & Toubro bags order", INDEX) == {LT.stock_id}


def test_multi_stock_article_tags_all() -> None:
    # QV-094 — the "Auto stocks rise…" case: an article naming two stocks links to both.
    assert match_all("Reliance Industries and Infosys both rallied", INDEX) == {
        RELIANCE.stock_id,
        INFY.stock_id,
    }


def test_no_match_returns_empty() -> None:
    assert match_all("Global markets mixed amid rate worries", INDEX) == set()


def test_non_unique_core_name_never_matches() -> None:
    a = StockRef(uuid4(), "ABCA", None, "Aditya Birla Capital Ltd")
    b = StockRef(uuid4(), "ABCB", None, "Aditya Birla Capital Ltd")  # same core → excluded at build
    idx = build_match_index([a, b])
    assert match_all("Aditya Birla Capital raises funds", idx) == set()


def test_substring_does_not_false_match() -> None:
    # "Infosys" must not match inside an unrelated longer word.
    assert match_all("Reinfosysation is not a company", INDEX) == set()


def test_short_alias_matches_name_without_trailing_india() -> None:
    # QV-094: "Kalyan Jewellers India Ltd" also matches the bare "Kalyan Jewellers" (≥2-token short
    # alias); but "Bank of India" must NOT degrade to the unsafe single word "bank".
    kalyan = StockRef(uuid4(), "KALYANKJIL", None, "Kalyan Jewellers India Ltd")
    boi = StockRef(uuid4(), "BANKINDIA", None, "Bank of India")
    idx = build_match_index([kalyan, boi])
    assert match_all("Indian Bank, Kalyan Jewellers lead midcap gains", idx) == {kalyan.stock_id}
    assert match_all("Bank of India cuts lending rate", idx) == {boi.stock_id}
    assert match_all("the bank raised rates", idx) == set()  # "bank" alone never tags
