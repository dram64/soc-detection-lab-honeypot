"""Tests for the session-level technique classifier (PROJECT_PLAN.md §8).

Classification rules:
  brute_force         — single IP, many failed logins of the same username
  credential_stuffing — single IP, 10+ unique usernames attempted
  scanner             — session < 2 s, connect/version only, no login attempts
  other               — anything else (incl. interesting cohort with successful login + commands)

The classifier consumes a *session summary* (counts + flags) so it can be
called from two places without re-implementing event walks:
  - the aggregator Lambda, on a single stream record (per-event partial summary)
  - any offline analysis tool, on a list of session events
"""

from __future__ import annotations

import pytest

from functions.shared.technique_classifier import (
    SessionSummary,
    classify_session,
    classify_event,
)


def _summary(**kwargs):
    base = dict(
        duration_seconds=10.0,
        login_failed_count=0,
        login_success_count=0,
        unique_usernames=0,
        command_count=0,
    )
    base.update(kwargs)
    return SessionSummary(**base)


def test_brute_force_single_username_many_failures():
    s = _summary(login_failed_count=50, unique_usernames=1, duration_seconds=30.0)
    assert classify_session(s) == "brute_force"


def test_brute_force_minimum_failures():
    # Threshold: brute_force requires >=5 failed logins of the same username
    s = _summary(login_failed_count=5, unique_usernames=1)
    assert classify_session(s) == "brute_force"


def test_below_brute_force_threshold_is_other():
    s = _summary(login_failed_count=3, unique_usernames=1)
    assert classify_session(s) == "other"


def test_credential_stuffing_many_usernames():
    s = _summary(login_failed_count=15, unique_usernames=10)
    assert classify_session(s) == "credential_stuffing"


def test_credential_stuffing_threshold_at_10():
    s = _summary(login_failed_count=10, unique_usernames=10)
    assert classify_session(s) == "credential_stuffing"


def test_credential_stuffing_with_one_success_still_credential_stuffing():
    s = _summary(login_failed_count=8, login_success_count=2, unique_usernames=10)
    assert classify_session(s) == "credential_stuffing"


def test_scanner_short_session_no_login():
    s = _summary(duration_seconds=1.5, login_failed_count=0, unique_usernames=0)
    assert classify_session(s) == "scanner"


def test_scanner_threshold_below_2s():
    s = _summary(duration_seconds=1.99, login_failed_count=0, unique_usernames=0)
    assert classify_session(s) == "scanner"


def test_short_session_with_login_is_not_scanner():
    s = _summary(duration_seconds=1.0, login_failed_count=1, unique_usernames=1)
    # Login attempt → not pure scanner; falls below brute-force threshold → other
    assert classify_session(s) == "other"


def test_interesting_session_with_commands_is_other():
    s = _summary(
        login_success_count=1,
        unique_usernames=1,
        command_count=5,
        duration_seconds=120.0,
    )
    assert classify_session(s) == "other"


def test_credential_stuffing_dominates_over_brute_force_when_both_apply():
    """If a session has 12 failed logins across 11 distinct usernames, the
    "many usernames" rule classifies it as credential_stuffing — not
    brute_force. This matches PROJECT_PLAN.md §8 cohort intent."""
    s = _summary(login_failed_count=12, unique_usernames=11)
    assert classify_session(s) == "credential_stuffing"


def test_classify_event_returns_none_for_non_terminal_events():
    # Per-event classification only makes sense at session.closed; everything
    # else returns None and the aggregator skips technique increments.
    assert classify_event({"eventid": "cowrie.session.connect"}) is None
    assert classify_event({"eventid": "cowrie.login.failed"}) is None


def test_classify_event_for_session_closed_with_summary():
    event = {
        "eventid": "cowrie.session.closed",
        "duration": 35.0,
    }
    summary = _summary(login_failed_count=10, unique_usernames=1, duration_seconds=35.0)
    assert classify_event(event, session_summary=summary) == "brute_force"


def test_classify_event_for_session_closed_without_summary_is_none():
    # Without a session summary, the aggregator can't classify alone.
    event = {"eventid": "cowrie.session.closed", "duration": 35.0}
    assert classify_event(event) is None


def test_summary_unique_usernames_must_be_non_negative():
    with pytest.raises(ValueError):
        SessionSummary(
            duration_seconds=1.0,
            login_failed_count=0,
            login_success_count=0,
            unique_usernames=-1,
            command_count=0,
        )
