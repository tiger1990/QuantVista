"""Non-advice language guard (QV-011).

`07` §1.2 requires that research output is never described as advice. A written guide alone decays —
one copy edit reads better, the posture is gone, and nothing notices until it matters. This scans
every user-facing string in both trees against `core.terminology` and fails the build on a breach.

Scope note: this is a *language* guard. It cannot judge whether a feature is advice; it stops the
product from describing itself as an adviser. Compliance review remains QV-086's job.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from quantvista.core.terminology import (
    ALLOWED_CONTEXTS,
    BANNED_PHRASES,
    PREFERRED_TERMS,
    is_allowed_context,
)

_REPO = Path(__file__).resolve().parents[2]
_GUIDE = _REPO / "docs" / "terminology-guide.md"

#: Where user-visible copy lives: frontend components/pages, plus API messages and email templates.
_SCAN_ROOTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("frontend/src", (".tsx", ".ts")),
    ("backend/src", (".py", ".j2", ".html")),
)

_SKIP_PARTS = ("node_modules", ".next", "__pycache__", "/migrations/")


def _user_facing_files() -> list[Path]:
    files: list[Path] = []
    for root, suffixes in _SCAN_ROOTS:
        base = _REPO / root
        if not base.exists():  # pragma: no cover - guards a repo layout change
            pytest.fail(f"scan root {base} is missing; the terminology guard is not covering it")
        for path in base.rglob("*"):
            text_path = str(path)
            if path.suffix not in suffixes or any(p in text_path for p in _SKIP_PARTS):
                continue
            if ".test." in path.name or ".spec." in path.name:
                continue  # tests assert *about* copy; they are not shipped copy
            files.append(path)
    return files


def test_the_guard_actually_scans_something() -> None:
    """A scanner that silently matched no files would pass everything below."""
    files = _user_facing_files()
    assert len(files) > 100, f"expected the whole app to be scanned, got {len(files)} files"


def test_no_user_facing_string_gives_investment_advice() -> None:
    """THE GUARD: research output must never be phrased as a recommendation to act."""
    breaches: list[str] = []
    for path in _user_facing_files():
        if is_allowed_context(str(path)):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):  # pragma: no cover - binary/unreadable stragglers
            continue
        for phrase in BANNED_PHRASES:
            for match in re.finditer(phrase.pattern, text, re.IGNORECASE):
                line = text[: match.start()].count("\n") + 1
                rel = path.relative_to(_REPO)
                breaches.append(
                    f"{rel}:{line} says {match.group(0)!r} — {phrase.why}. "
                    f"Instead: {phrase.instead}"
                )

    assert breaches == [], "advice-flavoured language in user-facing copy:\n  " + "\n  ".join(
        breaches
    )


def test_every_banned_phrase_is_documented_for_humans() -> None:
    """The rules and the written guide must not drift — a rule nobody can read is not a guide."""
    assert _GUIDE.exists(), f"{_GUIDE} is missing; the human half of QV-011 is not delivered"
    guide = _GUIDE.read_text(encoding="utf-8").lower()
    undocumented = [p.label for p in BANNED_PHRASES if p.label.lower() not in guide]
    assert undocumented == [], f"banned phrases missing from the guide: {undocumented}"


def test_preferred_terms_are_documented() -> None:
    guide = _GUIDE.read_text(encoding="utf-8").lower()
    missing = [term for term, _ in PREFERRED_TERMS if term.lower() not in guide]
    assert missing == [], f"preferred terms missing from the guide: {missing}"


def test_every_allowance_is_justified_and_real() -> None:
    """Each allowlisted file is a hole in the guard: it must exist and carry a reason."""
    for rel, reason in ALLOWED_CONTEXTS:
        assert reason.strip(), f"{rel} is allowlisted without a reason"
        assert (_REPO / rel).exists(), f"allowlisted path no longer exists — stale hole: {rel}"


def test_allowlist_stays_small() -> None:
    """The allowlist is the guard's weak point; growth should require deliberate thought."""
    assert len(ALLOWED_CONTEXTS) <= 5, (
        "the terminology allowlist is growing — each entry is copy the guard no longer checks; "
        "prefer rewording over adding an exemption"
    )
