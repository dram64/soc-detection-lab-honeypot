from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Technique = Literal["brute_force", "credential_stuffing", "scanner", "other"]

# Thresholds — keep these as named constants so Phase 11 (real-data tuning)
# has one obvious place to retune from observed reality.
SCANNER_MAX_DURATION_S = 2.0
CREDENTIAL_STUFFING_MIN_USERNAMES = 10
BRUTE_FORCE_MIN_FAILURES = 5


@dataclass(frozen=True)
class SessionSummary:
    duration_seconds: float
    login_failed_count: int
    login_success_count: int
    unique_usernames: int
    command_count: int

    def __post_init__(self) -> None:
        for name in (
            "login_failed_count",
            "login_success_count",
            "unique_usernames",
            "command_count",
        ):
            value = getattr(self, name)
            if value < 0:
                raise ValueError(f"{name} must be non-negative; got {value}")
        if self.duration_seconds < 0:
            raise ValueError(f"duration_seconds must be non-negative; got {self.duration_seconds}")

    @property
    def total_login_attempts(self) -> int:
        return self.login_failed_count + self.login_success_count


def classify_session(summary: SessionSummary) -> Technique:
    """Return the technique label for a closed session.

    Rule precedence (matters when a session matches multiple cohort shapes):
      1. credential_stuffing wins over brute_force when 10+ usernames are
         seen, even if there are also enough failures to qualify for
         brute_force on a single-username basis.
      2. brute_force fires only when a single username is repeatedly tried.
      3. scanner only applies to short sessions with no login activity.
      4. else → other.
    """
    if (
        summary.unique_usernames >= CREDENTIAL_STUFFING_MIN_USERNAMES
        and summary.total_login_attempts > 0
    ):
        return "credential_stuffing"

    if summary.login_failed_count >= BRUTE_FORCE_MIN_FAILURES and summary.unique_usernames == 1:
        return "brute_force"

    if summary.duration_seconds < SCANNER_MAX_DURATION_S and summary.total_login_attempts == 0:
        return "scanner"

    return "other"


def classify_event(
    event: dict, *, session_summary: SessionSummary | None = None
) -> Technique | None:
    """Per-event classification helper for the aggregator.

    Returns a technique label only on `cowrie.session.closed` events, and
    only when a `session_summary` is provided (the aggregator will have
    accumulated one over the lifetime of the session by then).

    Returns `None` for all other event types — these don't carry enough
    context to classify on their own. The aggregator simply skips technique
    increments for them.
    """
    if event.get("eventid") != "cowrie.session.closed":
        return None
    if session_summary is None:
        return None
    return classify_session(session_summary)


__all__ = [
    "BRUTE_FORCE_MIN_FAILURES",
    "CREDENTIAL_STUFFING_MIN_USERNAMES",
    "SCANNER_MAX_DURATION_S",
    "SessionSummary",
    "Technique",
    "classify_event",
    "classify_session",
]
