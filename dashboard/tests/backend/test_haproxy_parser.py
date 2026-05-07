"""Unit tests for functions.shared.haproxy_parser."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from functions.shared.haproxy_parser import (
    buckets_for_window,
    cowrie_ts_to_us,
    parse_record,
    to_ddb_item,
)


def _record() -> dict:
    return {
        "time": "2026-05-07T00:55:01.948594+00:00",
        "host": "soc-honeypot-ingress",
        "process": "haproxy",
        "pid": 12345,
        "client_ip": "104.174.33.78",
        "client_port": 8728,
        "frontend_port": 22,
        "duration": 67180,
        "bytes_uploaded": 2169,
        "bytes_downloaded": 1880,
        "status": "cD",
        "fluent_host": "droplet",
        "fluent_source": "haproxy",
    }


def test_parse_record_extracts_microsecond_timestamp():
    rec = parse_record(_record())
    assert rec is not None
    assert rec.client_ip == "104.174.33.78"
    assert rec.client_port == 8728
    assert rec.frontend_port == 22
    # ts_us is microseconds-since-epoch
    expected = int(
        datetime(2026, 5, 7, 0, 55, 1, 948594, tzinfo=UTC).timestamp() * 1_000_000
    )
    assert rec.ts_us == expected


def test_parse_record_normalizes_timestamp_string_to_canonical_form():
    raw = _record()
    raw["time"] = "2026-05-07T00:55:01.948594Z"  # alt notation
    rec = parse_record(raw)
    assert rec is not None
    assert rec.ts == "2026-05-07T00:55:01.948594+00:00"


def test_parse_record_returns_none_on_missing_field():
    raw = _record()
    del raw["client_ip"]
    assert parse_record(raw) is None


def test_parse_record_returns_none_on_bad_timestamp():
    raw = _record()
    raw["time"] = "not-a-timestamp"
    assert parse_record(raw) is None


def test_to_ddb_item_partition_key_is_minute_bucket():
    rec = parse_record(_record())
    assert rec is not None
    item = to_ddb_item(rec)
    assert item["pk"] == "HAPROXY#2026-05-07T00:55"
    assert item["sk"] == "2026-05-07T00:55:01.948594+00:00#8728"
    assert item["type"] == "HAPROXY_CONN"
    assert item["client_ip"] == "104.174.33.78"


def test_to_ddb_item_ttl_is_90_days_out_by_default():
    rec = parse_record(_record())
    assert rec is not None
    item = to_ddb_item(rec, ttl_days=90)
    expected_ttl_us = rec.ts_us + 90 * 86400 * 1_000_000
    assert abs(item["ttl"] * 1_000_000 - expected_ttl_us) < 2_000_000  # within 2s of microsecond math


def test_cowrie_ts_to_us_handles_both_z_and_offset_forms():
    a = cowrie_ts_to_us("2026-05-07T00:55:01.948594Z")
    b = cowrie_ts_to_us("2026-05-07T00:55:01.948594+00:00")
    assert a == b


def test_buckets_for_window_single_bucket_in_middle_of_minute():
    cowrie_us = cowrie_ts_to_us("2026-05-07T00:55:30.000000Z")
    buckets = buckets_for_window(cowrie_us, window_us=200_000)
    assert buckets == ["2026-05-07T00:55"]


def test_buckets_for_window_spans_two_when_near_minute_boundary():
    # ts is 50ms into minute; window is 200ms → start_us is 150ms into prev minute.
    cowrie_us = cowrie_ts_to_us("2026-05-07T00:55:00.050000Z")
    buckets = buckets_for_window(cowrie_us, window_us=200_000)
    assert buckets == ["2026-05-07T00:54", "2026-05-07T00:55"]


@pytest.mark.parametrize("port", [0, 22, 65535])
def test_parse_record_accepts_valid_port_range(port):
    raw = _record()
    raw["client_port"] = port
    raw["frontend_port"] = port
    rec = parse_record(raw)
    assert rec is not None
    assert rec.client_port == port
