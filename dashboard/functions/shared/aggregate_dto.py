"""Pydantic models for the aggregator's DDB items (PROJECT_PLAN.md §4).

Three item shapes:
  HourlyCounter — per (dimension, hour, value) running tally; updated atomically
                  via UpdateExpression "ADD count :inc" by the stream handler.
  RankItem      — top-N projection rebuilt by the EventBridge scheduler from
                  the trailing window of HourlyCounter items.
  DailySummary  — once-per-day rollup written at 00:05 UTC.

These are the WRITE surfaces. The API surface (PublicEvent etc.) lives in
event_dto.py. Keeping them split prevents a buggy line in one path from
projecting fields it shouldn't.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Dimension = Literal[
    "username",
    "password",
    "country",
    "asn",
    "eventid",
    "technique",
]

RankWindow = Literal["24H", "7D"]


class HourlyCounter(BaseModel):
    """Per-(dimension, hour-bucket, value) running count.

    pk = AGG#HOUR#<hour-bucket>#<dimension>
    sk = VALUE#<value>
    """

    model_config = ConfigDict(extra="forbid")

    pk: str
    sk: str
    type: Literal["AGG_COUNT"] = "AGG_COUNT"
    dimension: Dimension
    value: str
    bucket: str  # e.g. "2026-04-28T14"
    count: int = Field(ge=0)
    ttl: int

    @classmethod
    def key_for(cls, *, bucket: str, dimension: Dimension, value: str) -> dict[str, str]:
        return {
            "pk": f"AGG#HOUR#{bucket}#{dimension}",
            "sk": f"VALUE#{value}",
        }


def rank_sk(count: int, value: str) -> str:
    """Sort-key form for descending rank order.

    DynamoDB sorts strings ascending; inverting the count via subtraction
    from a fixed ceiling makes the largest count sort first when the GSI is
    queried with the default ScanIndexForward=True (and equivalently with
    ScanIndexForward=False — the inversion is the load-bearing trick).

    Ten zero-padded digits is enough for any count we'd ever see at honeypot
    scale (max ~9.9 billion per dimension+window).
    """
    return f"{9_999_999_999 - count:010d}#{value}"


class RankItem(BaseModel):
    """Top-N rank projection for a (window, dimension) tuple.

    pk = RANK#<window>#<dimension>
    sk = <inverted-count>#<value>     (so DDB sorts highest-count first)
    """

    model_config = ConfigDict(extra="forbid")

    pk: str
    sk: str
    gsi3pk: str
    gsi3sk: str
    type: Literal["RANK"] = "RANK"
    window: RankWindow
    dimension: Dimension
    value: str
    count: int = Field(ge=0)
    ttl: int


class DailySummary(BaseModel):
    """One row per UTC day with hand-picked top-line counters.

    pk = SUMMARY#DAY
    sk = YYYY-MM-DD
    """

    model_config = ConfigDict(extra="forbid")

    pk: Literal["SUMMARY#DAY"] = "SUMMARY#DAY"
    sk: str  # YYYY-MM-DD
    type: Literal["SUMMARY"] = "SUMMARY"
    day: str  # YYYY-MM-DD; mirrors sk for query convenience
    total_events: int = Field(ge=0)
    unique_ips: int = Field(ge=0)
    unique_sessions: int = Field(ge=0)
    successful_logins: int = Field(ge=0)
    file_downloads: int = Field(ge=0)
    techniques: dict[str, int]


__all__ = [
    "DailySummary",
    "Dimension",
    "HourlyCounter",
    "RankItem",
    "RankWindow",
    "rank_sk",
]
