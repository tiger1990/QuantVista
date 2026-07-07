"""Opaque keyset cursors (QV-032).

The cursor is base64(last sort-key) — opaque to clients, stable under inserts (keyset, not OFFSET).
`/stocks` keys on the unique ``symbol``; a bad cursor is a validation error, not a 500.
"""

from __future__ import annotations

import base64
import binascii


class InvalidCursor(Exception):
    """A malformed pagination cursor → mapped to a 422 `validation_error` envelope."""


def encode_cursor(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode()).decode()


def decode_cursor(cursor: str | None) -> str | None:
    """Decode an opaque cursor to its sort-key; ``None`` passes through. Raises on garbage."""
    if not cursor:
        return None
    try:
        return base64.urlsafe_b64decode(cursor.encode()).decode()
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise InvalidCursor("invalid cursor") from exc
