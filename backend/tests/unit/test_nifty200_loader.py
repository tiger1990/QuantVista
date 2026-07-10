"""Unit tests for the QV-092 Nifty-200 dev loader's pure CSV parser."""

from __future__ import annotations

from pathlib import Path

from load_nifty200_universe import DATA_FILE, ConstituentRow, parse_nifty200_csv

SAMPLE = (
    "Company Name,Industry,Symbol,Series,ISIN Code\n"
    "360 ONE WAM Ltd.,Financial Services,360ONE,EQ,INE466L01038\n"
    "ABB India Ltd.,Capital Goods,ABB,EQ,INE117A01022\n"
    "\n"  # blank line is skipped
    ",,,EQ,\n"  # symbol-less line is skipped
)


def test_parse_maps_columns_and_skips_blank_lines() -> None:
    rows = parse_nifty200_csv(SAMPLE)
    assert rows == [
        ConstituentRow("360ONE", "360 ONE WAM Ltd.", "Financial Services", "INE466L01038"),
        ConstituentRow("ABB", "ABB India Ltd.", "Capital Goods", "INE117A01022"),
    ]


def test_bundled_csv_has_the_full_nifty_200() -> None:
    rows = parse_nifty200_csv(Path(DATA_FILE).read_text(encoding="utf-8"))
    assert len(rows) == 200
    # Symbols are unique and non-empty; a known large-cap is present.
    symbols = {r.symbol for r in rows}
    assert len(symbols) == 200
    assert "RELIANCE" in symbols
    # Every row carries a company name and an NSE ISIN.
    assert all(r.company_name and r.isin.startswith("INE") for r in rows)
