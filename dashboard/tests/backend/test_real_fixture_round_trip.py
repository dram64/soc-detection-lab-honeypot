"""Real-data round-trip tests for the Cowrie schema.

Phase 11A: every fixture under tests/backend/fixtures/real_data/ was
captured from the live honeypot (sanitized via fixtures/sanitize.py).
These tests lock in the actual on-the-wire shapes so a future
schema tweak that breaks real-attacker traffic fails CI loudly
instead of silently dropping events at the parser.

A failure here means: the parser stopped accepting a Cowrie event
shape that we know lands in the wild. Either fix the schema or
re-capture+sanitize the fixture if Cowrie itself changed the shape.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from functions.shared.cowrie_schema import CowrieEvent

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "real_data"


def _all_fixtures() -> list[Path]:
    return sorted(FIXTURES_DIR.glob("cowrie_*.json"))


def test_fixtures_dir_is_populated():
    """Catch a missing/renamed fixtures dir before the parametrized cases
    silently report 'no tests'."""
    fixtures = _all_fixtures()
    assert len(fixtures) >= 7, (
        f"expected >=7 real fixtures spanning all observed eventids; "
        f"found {len(fixtures)} in {FIXTURES_DIR}"
    )


@pytest.mark.parametrize(
    "fixture_path",
    _all_fixtures(),
    ids=lambda p: p.stem,
)
def test_real_fixture_validates_clean(fixture_path: Path) -> None:
    """Each sanitized real-data event must validate without ValidationError."""
    raw = json.loads(fixture_path.read_text(encoding="utf-8"))
    event = CowrieEvent.model_validate(raw)
    # And cross-field checks must pass — these are the per-eventid
    # required-field invariants in check_fields().
    event.check_fields()


@pytest.mark.parametrize(
    "fixture_path",
    _all_fixtures(),
    ids=lambda p: p.stem,
)
def test_real_fixture_carries_no_chat_disclosed_or_user_pc_data(
    fixture_path: Path,
) -> None:
    """Defensive check on the sanitization pass — fixtures must not carry
    the maintainer's home IP or any password_raw remnant."""
    body = fixture_path.read_text(encoding="utf-8")
    assert "104.174.33.78" not in body, (
        f"{fixture_path.name} still has the maintainer's home IP; "
        "re-run sanitize_for_fixture()"
    )
    assert "password_raw" not in body, (
        f"{fixture_path.name} contains password_raw — ADR-005 boundary; "
        "re-sanitize before commit"
    )
    assert "fluent_host" not in body and "fluent_source" not in body, (
        f"{fixture_path.name} contains fluent-bit transport metadata; "
        "re-sanitize before commit"
    )


def test_session_params_message_can_be_a_list() -> None:
    """Cowrie occasionally ships `cowrie.session.params` with `message: []`
    instead of the usual string. Phase 11A loosened the field type to
    accept both shapes."""
    raw = json.loads(
        (FIXTURES_DIR / "cowrie_session_params.json").read_text(encoding="utf-8")
    )
    assert isinstance(raw["message"], list), "fixture should reflect the list shape"
    event = CowrieEvent.model_validate(raw)
    assert event.message == []


def test_log_closed_with_unknown_extras_is_accepted() -> None:
    """Cowrie 2.x's cowrie.log.closed carries `ttylog`, `size`, `duplicate`
    fields that the schema doesn't declare. Phase 11A switched extra=
    'forbid' to 'ignore' so per-version Cowrie evolution doesn't drop
    entire batches at the parser."""
    raw = json.loads(
        (FIXTURES_DIR / "cowrie_log_closed.json").read_text(encoding="utf-8")
    )
    # Confirm the fixture actually carries the extras we widened the
    # schema for — otherwise the test would silently pass on tomorrow's
    # cleaner Cowrie release.
    assert "ttylog" in raw and "size" in raw and "duplicate" in raw
    event = CowrieEvent.model_validate(raw)
    # The extras drop on the floor under extra="ignore"; we don't surface
    # them as model attributes (intentionally — the schema only declares
    # what downstream consumers need).
    assert not hasattr(event, "ttylog")


def test_client_kex_with_unknown_extras_is_accepted() -> None:
    """Cowrie's cowrie.client.kex grew `hasshAlgorithms` and `langCS`
    fields that pre-Phase 11A `extra='forbid'` was rejecting (~48
    events/hour dropped). Phase 11A accepts them via extra='ignore'."""
    raw = json.loads(
        (FIXTURES_DIR / "cowrie_client_kex.json").read_text(encoding="utf-8")
    )
    assert "hasshAlgorithms" in raw and "langCS" in raw
    event = CowrieEvent.model_validate(raw)
    # hassh is the load-bearing fingerprint — must still parse + flow through.
    assert event.hassh is not None
    assert len(event.hassh) >= 32  # md5 hex
