"""Pydantic request and response DTOs for the API Lambda (PROJECT_PLAN.md §5).

Response models live here, not in event_dto.py, because:
  - event_dto.py defines `PublicEvent` (per-event projection that drops
    password_raw) — the load-bearing security boundary, kept narrow.
  - This file composes PublicEvent with the API-level wrappers
    (lists, paginators, summary aggregations).

Every response model uses `extra="forbid"` so any future bug that tries
to populate an undeclared field (such as `password_raw`) will fail
loudly at construction time rather than silently leaking.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from functions.shared.event_dto import PublicEvent

Window24h7d = Literal["24h", "7d"]
Window24h7d30d = Literal["24h", "7d", "30d"]
TimelineBucket = Literal["1h", "1d"]


# ---------------------------------------------------------------------------
# Request param validation
# ---------------------------------------------------------------------------


class TopListParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limit: Annotated[int, Field(ge=1, le=50)] = 20
    window: Window24h7d = "24h"


class TopAsnsParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limit: Annotated[int, Field(ge=1, le=25)] = 10
    window: Window24h7d = "24h"


class TimelineParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bucket: TimelineBucket = "1h"
    window: Window24h7d30d = "24h"


class EventsParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limit: Annotated[int, Field(ge=1, le=200)] = 50
    before: str | None = None  # ISO 8601 timestamp


class BreakdownParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    window: Window24h7d = "24h"


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["ok"]
    version: str


class SummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    total: int = Field(ge=0)
    last_24h: int = Field(ge=0)
    last_1h: int = Field(ge=0)
    unique_ips_24h: int = Field(ge=0)
    sensor_last_seen: str | None


class TimelineBucketRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ts: str
    # `None` indicates the underlying per-bucket DDB query failed; the
    # frontend can render that as a gap rather than a zero. Successful
    # buckets always carry a non-negative count.
    count: int | None = Field(default=None, ge=0)


class TimelineResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    buckets: list[TimelineBucketRow]


class TopListItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str
    count: int = Field(ge=0)


class TopListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[TopListItem]


class TopAsnItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asn: int
    asn_org: str | None
    count: int = Field(ge=0)


class TopAsnsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[TopAsnItem]


class EventsResponse(BaseModel):
    """Public event list — composes `PublicEvent`, which has `extra="forbid"`
    and explicitly does NOT declare `password_raw`. Any code path that tries
    to populate `password_raw` here fails at validation time."""

    model_config = ConfigDict(extra="forbid")
    items: list[PublicEvent]
    next_before: str | None


class BreakdownResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    brute_force: int = Field(ge=0)
    credential_stuffing: int = Field(ge=0)
    scanner: int = Field(ge=0)
    other: int = Field(ge=0)


class SessionEventsResponse(BaseModel):
    """Per-session detail (also uses PublicEvent — same password_raw guarantee)."""

    model_config = ConfigDict(extra="forbid")
    events: list[PublicEvent]


__all__ = [
    "TopListParams",
    "TopAsnsParams",
    "TimelineParams",
    "EventsParams",
    "BreakdownParams",
    "HealthResponse",
    "SummaryResponse",
    "TimelineResponse",
    "TimelineBucketRow",
    "TopListResponse",
    "TopListItem",
    "TopAsnsResponse",
    "TopAsnItem",
    "EventsResponse",
    "BreakdownResponse",
    "SessionEventsResponse",
]
