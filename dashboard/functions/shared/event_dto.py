from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StoredEvent(BaseModel):
    """The shape of a raw-event item written to DynamoDB.

    Includes `password_raw` for non-dictionary password attempts (ADR-005).
    This model represents the WRITE surface; it is never serialized as an
    API response.
    """

    model_config = ConfigDict(extra="forbid")

    # DDB keys (PROJECT_PLAN.md §4)
    pk: str
    sk: str
    gsi1pk: str
    gsi1sk: str
    gsi2pk: str
    gsi2sk: str

    type: str = "EVENT"
    eventid: str
    session: str
    src_ip: str
    sensor: str
    ts: str
    ingest_id: str
    ttl: int

    # Cowrie-source fields (kept verbatim per ADR-001)
    src_port: int | None = None
    dst_ip: str | None = None
    dst_port: int | None = None
    protocol: str | None = None
    sensor_uuid: str | None = None
    message: str | None = None

    username: str | None = None
    password: str | None = None
    password_raw: str | None = None  # NEVER returned by the API

    version: str | None = None
    hassh: str | None = None
    input: str | None = None
    url: str | None = None
    outfile: str | None = None
    shasum: str | None = None
    duration: float | None = None

    # Enrichment (added at ingest time)
    country: str | None = None
    asn: int | None = None
    asn_org: str | None = None

    # Correlation status from the HAProxy join (ADR-010).
    # matched   : src_ip rewritten to the real attacker IP from HAProxy
    # missed    : no HAProxy candidate in the time window; src_ip kept as-is
    # ambiguous : >1 HAProxy candidate; src_ip kept as-is, candidates listed
    correlation_status: str | None = None
    correlation_candidate_count: int | None = None
    correlation_candidate_ips: list[str] | None = None


class PublicEvent(BaseModel):
    """The shape of a single event as returned by the API (e.g. /api/events).

    This is the contract the frontend consumes. Crucially, it does NOT
    include `password_raw` — Pydantic's `extra="forbid"` guarantees that
    even if a future bug accidentally tries to populate it, instantiation
    fails loudly rather than silently leaking the redacted value.
    """

    model_config = ConfigDict(extra="forbid")

    eventid: str
    session: str
    src_ip: str
    ts: str
    sensor: str

    src_port: int | None = None
    dst_ip: str | None = None
    dst_port: int | None = None
    protocol: str | None = None
    message: str | None = None

    username: str | None = None
    password: str | None = None  # dictionary-classified or <filtered:len=N>

    input: str | None = None
    url: str | None = None
    shasum: str | None = None
    duration: float | None = None

    country: str | None = None
    asn: int | None = None
    asn_org: str | None = None

    # Surfaced to the dashboard so it can render the three-state correlation
    # honestly (matched IP / `127.0.0.1 (correlation ambiguous)` / `127.0.0.1 (no match)`).
    correlation_status: str | None = None

    @classmethod
    def from_stored(cls, stored: StoredEvent) -> "PublicEvent":
        """Project a StoredEvent down to the public DTO.

        password_raw is dropped on the floor here. This is the only sanctioned
        path from a stored item to an API response.
        """
        payload = stored.model_dump(exclude_none=False)
        payload.pop("password_raw", None)
        # Keep only fields PublicEvent declares; ConfigDict.extra=forbid
        # would otherwise reject inherited DDB key attributes.
        allowed = set(cls.model_fields.keys())
        return cls.model_validate({k: v for k, v in payload.items() if k in allowed})


def is_password_raw_in_serialized(payload: dict[str, Any]) -> bool:
    """Test helper used by the regression suite to confirm `password_raw`
    never appears in a JSON-serializable dict produced by PublicEvent.
    """
    return "password_raw" in payload
