"""Opaque cursor round-trip (QV-032) — encode/decode + garbage handling."""

from __future__ import annotations

import pytest

from quantvista.api.pagination import InvalidCursor, decode_cursor, encode_cursor


def test_cursor_round_trip() -> None:
    for value in ("RELIANCE", "TCS", "a-symbol.with:chars"):
        assert decode_cursor(encode_cursor(value)) == value


def test_none_cursor_passes_through() -> None:
    assert decode_cursor(None) is None
    assert decode_cursor("") is None


def test_garbage_cursor_raises_invalid() -> None:
    with pytest.raises(InvalidCursor):
        decode_cursor("!!!not-base64!!!")
