from __future__ import annotations

from pathlib import Path

DICTIONARY_PATH = Path(__file__).resolve().parent / "data" / "password_dictionary.txt"


def load_dictionary(path: Path | None = None) -> frozenset[str]:
    """Read the dictionary file into a frozenset.

    Lines beginning with ``#`` and blank lines are ignored. Whitespace around
    each entry is stripped so trailing spaces in the source file don't
    accidentally produce non-matches. Each remaining line is one literal
    password.
    """
    target = path if path is not None else DICTIONARY_PATH
    entries: set[str] = set()
    with target.open("r", encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            entries.add(line)
    return frozenset(entries)


def classify_password(
    attempted: str | None, dictionary: frozenset[str]
) -> tuple[str | None, str | None]:
    """Classify an attempted password.

    Returns ``(public, raw)``:
      - ``public`` — the value to store as `password` (visible to the API).
        Either the original (dictionary hit) or ``<filtered:len=N>``.
      - ``raw`` — the value to store as `password_raw` (never returned by API).
        ``None`` for dictionary hits; the original value for non-matches.

    Defensive: a `None` input returns ``(None, None)`` — Cowrie events without
    a password field shouldn't reach this function, but if they do we don't
    invent a redaction marker.

    This function MUST NOT log the raw value, ever — see the corresponding test.
    """
    if attempted is None:
        return None, None
    if attempted in dictionary:
        return attempted, None
    return f"<filtered:len={len(attempted)}>", attempted
