"""Direct tests for the aggregator's pure helpers (no AWS needed)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from functions.aggregator.handler import (
    _hour_bucket,
    _hourly_ttl,
    _rank_ttl,
    _summary_ttl,
    _unmarshal_dynamodb_value,
    _unmarshal_image,
)


def test_hour_bucket_strips_to_hour():
    assert _hour_bucket("2026-04-28T14:05:00.123456Z") == "2026-04-28T14"
    assert _hour_bucket("2026-04-28T00:00:00.000000Z") == "2026-04-28T00"


def test_hourly_ttl_is_60_days_after_bucket():
    ttl = _hourly_ttl("2026-04-28T14")
    expected = datetime(2026, 6, 27, 14, tzinfo=timezone.utc).timestamp()
    assert ttl == int(expected)


def test_rank_ttl_is_in_the_future():
    now = int(datetime.now(timezone.utc).timestamp())
    assert _rank_ttl() > now


def test_summary_ttl_is_far_future():
    ttl = _summary_ttl("2026-04-28")
    now = int(datetime.now(timezone.utc).timestamp())
    assert ttl > now + (300 * 86400)


def test_unmarshal_string():
    assert _unmarshal_dynamodb_value({"S": "hello"}) == "hello"


def test_unmarshal_int():
    assert _unmarshal_dynamodb_value({"N": "42"}) == 42


def test_unmarshal_float():
    assert _unmarshal_dynamodb_value({"N": "3.5"}) == 3.5


def test_unmarshal_null():
    assert _unmarshal_dynamodb_value({"NULL": True}) is None


def test_unmarshal_bool():
    assert _unmarshal_dynamodb_value({"BOOL": True}) is True
    assert _unmarshal_dynamodb_value({"BOOL": False}) is False


def test_unmarshal_list():
    out = _unmarshal_dynamodb_value({"L": [{"S": "a"}, {"N": "1"}]})
    assert out == ["a", 1]


def test_unmarshal_map():
    out = _unmarshal_dynamodb_value({"M": {"k": {"S": "v"}, "n": {"N": "7"}}})
    assert out == {"k": "v", "n": 7}


def test_unmarshal_unknown_returns_none():
    # Defensive — unknown type tag shouldn't crash the aggregator.
    assert _unmarshal_dynamodb_value({"B": "binary"}) is None


def test_unmarshal_image_round_trip():
    out = _unmarshal_image(
        {
            "pk": {"S": "SESSION#abc"},
            "count": {"N": "42"},
            "duration": {"N": "30.5"},
            "active": {"BOOL": True},
            "missing": {"NULL": True},
        }
    )
    assert out == {
        "pk": "SESSION#abc",
        "count": 42,
        "duration": 30.5,
        "active": True,
        "missing": None,
    }
