"""Regression tests guarding the password_raw → API leakage boundary."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from functions.shared.event_dto import (
    PublicEvent,
    StoredEvent,
    is_password_raw_in_serialized,
)


def _stored(**overrides) -> StoredEvent:
    base = {
        "pk": "SESSION#abcd1234",
        "sk": "2026-04-27T23:19:26.097161Z#cowrie.login.failed",
        "gsi1pk": "IP#192.0.2.5",
        "gsi1sk": "2026-04-27T23:19:26.097161Z",
        "gsi2pk": "DAY#2026-04-27",
        "gsi2sk": "2026-04-27T23:19:26.097161Z#SESSION#abcd1234",
        "eventid": "cowrie.login.failed",
        "session": "abcd1234",
        "src_ip": "192.0.2.5",
        "sensor": "honeypot",
        "ts": "2026-04-27T23:19:26.097161Z",
        "ingest_id": "sha1:deadbeef",
        "ttl": 1735689600,
        "username": "root",
        "password": "<filtered:len=14>",
        "password_raw": "private!hunter2x",
        "country": "DE",
        "asn": 24940,
        "asn_org": "Hetzner Online GmbH",
    }
    base.update(overrides)
    return StoredEvent(**base)


def test_stored_event_carries_password_raw():
    stored = _stored()
    assert stored.password_raw == "private!hunter2x"


def test_public_event_rejects_password_raw_field():
    payload = {
        "eventid": "cowrie.login.failed",
        "session": "abcd1234",
        "src_ip": "192.0.2.5",
        "ts": "2026-04-27T23:19:26.097161Z",
        "sensor": "honeypot",
        "password": "<filtered:len=14>",
        "password_raw": "should not be allowed",
    }
    with pytest.raises(ValidationError) as exc:
        PublicEvent(**payload)
    assert "password_raw" in str(exc.value)


def test_from_stored_drops_password_raw():
    stored = _stored()
    public = PublicEvent.from_stored(stored)
    serialized = public.model_dump()
    assert "password_raw" not in serialized
    assert not is_password_raw_in_serialized(serialized)
    assert public.password == "<filtered:len=14>"


def test_from_stored_preserves_dictionary_hit_password():
    stored = _stored(password="123456", password_raw=None)
    public = PublicEvent.from_stored(stored)
    assert public.password == "123456"
    assert "password_raw" not in public.model_dump()


def test_json_dump_never_contains_password_raw():
    stored = _stored()
    public = PublicEvent.from_stored(stored)
    serialized_str = public.model_dump_json()
    assert "password_raw" not in serialized_str
    parsed = json.loads(serialized_str)
    assert "password_raw" not in parsed


def test_stored_event_extra_fields_rejected():
    with pytest.raises(ValidationError):
        _stored(unknown_field="bad")


def test_public_event_extra_fields_rejected():
    with pytest.raises(ValidationError):
        PublicEvent(
            eventid="cowrie.login.failed",
            session="abcd1234",
            src_ip="192.0.2.5",
            ts="2026-04-27T23:19:26.097161Z",
            sensor="honeypot",
            unknown_field="bad",  # type: ignore[call-arg]
        )
