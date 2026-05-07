"""Pydantic DTO tests for the API surface.

Most importantly: the password_raw non-leakage contract test.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from functions.shared.api_dto import (
    BreakdownParams,
    EventsParams,
    EventsResponse,
    SessionEventsResponse,
    TimelineParams,
    TopListParams,
)
from functions.shared.event_dto import PublicEvent, StoredEvent


def _stored(**overrides) -> StoredEvent:
    base = {
        "pk": "SESSION#abcd1234",
        "sk": "2026-04-29T12:00:00.000000Z#cowrie.login.failed",
        "gsi1pk": "IP#192.0.2.5",
        "gsi1sk": "2026-04-29T12:00:00.000000Z",
        "gsi2pk": "DAY#2026-04-29",
        "gsi2sk": "2026-04-29T12:00:00.000000Z#SESSION#abcd1234",
        "eventid": "cowrie.login.failed",
        "session": "abcd1234",
        "src_ip": "192.0.2.5",
        "sensor": "honeypot",
        "ts": "2026-04-29T12:00:00.000000Z",
        "ingest_id": "sha1:abcd",
        "ttl": 1820000000,
        "username": "root",
        "password": "<filtered:len=14>",
        "password_raw": "extremely-private-secret-do-not-leak",
    }
    base.update(overrides)
    return StoredEvent(**base)


def test_top_list_params_default():
    p = TopListParams()
    assert p.limit == 20
    assert p.window == "24h"


def test_top_list_params_limit_bounds():
    with pytest.raises(ValidationError):
        TopListParams(limit=0)
    with pytest.raises(ValidationError):
        TopListParams(limit=51)


def test_timeline_params_invalid_window():
    with pytest.raises(ValidationError):
        TimelineParams(window="bogus")


def test_events_params_limit_upper_bound():
    with pytest.raises(ValidationError):
        EventsParams(limit=201)


def test_breakdown_params_window_enum():
    BreakdownParams(window="24h")
    BreakdownParams(window="7d")
    with pytest.raises(ValidationError):
        BreakdownParams(window="30d")  # not in this endpoint's enum


# ------------------------------------------------------------------ password_raw


def test_events_response_rejects_extra_password_raw_field():
    """Building EventsResponse from a dict containing password_raw must fail."""
    raw = {
        "items": [
            {
                "eventid": "cowrie.login.failed",
                "session": "abcd1234",
                "src_ip": "192.0.2.5",
                "ts": "2026-04-29T12:00:00.000000Z",
                "sensor": "honeypot",
                "username": "root",
                "password": "<filtered:len=14>",
                "password_raw": "leak",
            }
        ],
        "next_before": None,
    }
    with pytest.raises(ValidationError) as exc:
        EventsResponse.model_validate(raw)
    assert "password_raw" in str(exc.value)


def test_events_response_from_stored_drops_password_raw():
    """Round-trip: stored items projected through PublicEvent.from_stored
    yield an EventsResponse whose JSON contains no `password_raw` token."""
    stored = _stored()
    public = PublicEvent.from_stored(stored)
    response = EventsResponse(items=[public], next_before=None)

    serialized = response.model_dump_json()
    assert "password_raw" not in serialized
    assert "extremely-private-secret-do-not-leak" not in serialized

    parsed = json.loads(serialized)
    item = parsed["items"][0]
    assert "password_raw" not in item
    assert item["password"] == "<filtered:len=14>"


def test_events_response_with_dictionary_match_preserves_password():
    """Dictionary-classified passwords (no password_raw) flow through."""
    stored = _stored(password="123456", password_raw=None)
    public = PublicEvent.from_stored(stored)
    response = EventsResponse(items=[public], next_before=None)

    parsed = json.loads(response.model_dump_json())
    assert parsed["items"][0]["password"] == "123456"
    assert "password_raw" not in parsed["items"][0]


def test_session_events_response_drops_password_raw():
    """Same guarantee on the per-session detail endpoint."""
    stored1 = _stored(password_raw="raw-1")
    stored2 = _stored(password_raw="raw-2", session="abcd1234")
    public1 = PublicEvent.from_stored(stored1)
    public2 = PublicEvent.from_stored(stored2)
    resp = SessionEventsResponse(events=[public1, public2])
    serialized = resp.model_dump_json()
    assert "password_raw" not in serialized
    assert "raw-1" not in serialized
    assert "raw-2" not in serialized


def test_no_api_dto_class_declares_password_raw():
    """Defensive: walk every response model in api_dto and confirm none
    declares a `password_raw` field. A future programmer who forgets the
    boundary still gets caught here."""
    from pydantic import BaseModel

    import functions.shared.api_dto as api_dto

    leakers: list[str] = []
    for name in dir(api_dto):
        obj = getattr(api_dto, name)
        if (
            isinstance(obj, type)
            and issubclass(obj, BaseModel)
            and "password_raw" in obj.model_fields
        ):
            leakers.append(name)
    assert leakers == [], f"DTOs declaring password_raw: {leakers}"
