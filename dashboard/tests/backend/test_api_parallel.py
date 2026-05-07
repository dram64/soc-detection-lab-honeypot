"""Tests for the API Lambda's parallelization fixes (timeline / breakdown / summary)."""

from __future__ import annotations

import json
import time
from importlib import reload
from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws

TABLE = "dram-soc-honeypot"


@pytest.fixture(autouse=True)
def aws_creds(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("DDB_TABLE", TABLE)


def _create_table(ddb):
    ddb.create_table(
        TableName=TABLE,
        AttributeDefinitions=[
            {"AttributeName": "pk", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "pk", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )


def _import_handler():
    import functions.api.handler as h

    return reload(h)


def _event(route_key: str, *, query=None, path=None) -> dict:
    return {
        "routeKey": route_key,
        "queryStringParameters": query,
        "pathParameters": path,
    }


# ------------------------------------------------------------- run_parallel


@mock_aws
def test_run_parallel_collects_all_successes():
    boto3.client("dynamodb", region_name="us-east-1")
    _create_table(boto3.client("dynamodb", region_name="us-east-1"))
    h = _import_handler()
    work = list(range(24))
    out, fails = h._run_parallel(work, lambda x: x * 2, label="t")
    assert sorted(out) == [i * 2 for i in range(24)]
    assert fails == []


@mock_aws
def test_run_parallel_isolates_failures():
    boto3.client("dynamodb", region_name="us-east-1")
    _create_table(boto3.client("dynamodb", region_name="us-east-1"))
    h = _import_handler()

    def fn(x):
        if x == 7:
            raise RuntimeError("simulated")
        return x * 10

    out, fails = h._run_parallel(list(range(10)), fn, label="t")
    assert sorted(out) == [i * 10 for i in range(10) if i != 7]
    assert len(fails) == 1
    assert fails[0][0] == 7
    assert isinstance(fails[0][1], RuntimeError)


@mock_aws
def test_run_parallel_actually_parallel():
    """24 sleep(50ms) callables in parallel must finish well under 1.2s
    (the sequential cost). We bar at 400ms — generous to avoid flakes."""
    boto3.client("dynamodb", region_name="us-east-1")
    _create_table(boto3.client("dynamodb", region_name="us-east-1"))
    h = _import_handler()

    def slow(x):
        time.sleep(0.05)  # 50ms
        return x

    work = list(range(24))
    start = time.perf_counter()
    out, _ = h._run_parallel(work, slow, label="t")
    elapsed = time.perf_counter() - start
    assert elapsed < 0.4, f"parallel run took {elapsed:.3f}s; sequential would be ~1.2s"
    assert sorted(out) == sorted(work)


# ------------------------------------------------------------- timeline parallel


@mock_aws
def test_timeline_runs_queries_in_parallel():
    """Patch the per-bucket helper to sleep, verify wall-clock is parallel-fast."""
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(ddb)
    h = _import_handler()

    real_helper = h._query_one_hour_eventid_bucket

    def slow_helper(bucket_dt):
        time.sleep(0.05)  # 50ms
        return real_helper(bucket_dt)

    with patch.object(h, "_query_one_hour_eventid_bucket", side_effect=slow_helper):
        start = time.perf_counter()
        resp = h.handler(_event("GET /api/timeline"), context=None)
        elapsed = time.perf_counter() - start
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert len(body["buckets"]) == 24
    # 24 x 50ms sequential would be 1.2s. Parallel with max_workers=10
    # tops out around (24/10) x 50ms = 120ms + overhead.
    assert elapsed < 0.5, f"timeline took {elapsed:.3f}s; parallelization not effective"


@mock_aws
def test_timeline_failed_bucket_returns_count_none():
    """One bad query among 24 must surface as count=None, not crash the endpoint."""
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(ddb)
    h = _import_handler()

    real_helper = h._query_one_hour_eventid_bucket
    bomb_target = h._now_utc() - __import__("datetime").timedelta(hours=5)
    bomb_str = bomb_target.strftime("%Y-%m-%dT%H")

    def maybe_bomb(bucket_dt):
        if bucket_dt.strftime("%Y-%m-%dT%H") == bomb_str:
            raise RuntimeError("simulated DDB failure")
        return real_helper(bucket_dt)

    with patch.object(h, "_query_one_hour_eventid_bucket", side_effect=maybe_bomb):
        resp = h.handler(_event("GET /api/timeline"), context=None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert len(body["buckets"]) == 24
    # 23 buckets have integer count, 1 has count=None
    none_count = sum(1 for b in body["buckets"] if b["count"] is None)
    int_count = sum(1 for b in body["buckets"] if isinstance(b["count"], int))
    assert none_count == 1, f"expected 1 None bucket, got {none_count}"
    assert int_count == 23


# ------------------------------------------------------------- breakdown parallel


@mock_aws
def test_breakdown_runs_queries_in_parallel():
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(ddb)
    h = _import_handler()

    real_helper = h._query_one_hour_technique_bucket

    def slow(bucket_dt):
        time.sleep(0.05)
        return real_helper(bucket_dt)

    with patch.object(h, "_query_one_hour_technique_bucket", side_effect=slow):
        start = time.perf_counter()
        resp = h.handler(_event("GET /api/breakdown"), context=None)
        elapsed = time.perf_counter() - start
    assert resp["statusCode"] == 200
    assert elapsed < 0.5, f"breakdown took {elapsed:.3f}s; parallelization not effective"


@mock_aws
def test_breakdown_skips_failed_hours():
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(ddb)
    h = _import_handler()

    real_helper = h._query_one_hour_technique_bucket
    call_count = {"i": 0}

    def maybe_fail(bucket_dt):
        call_count["i"] += 1
        if call_count["i"] == 5:
            raise RuntimeError("simulated")
        return real_helper(bucket_dt)

    with patch.object(h, "_query_one_hour_technique_bucket", side_effect=maybe_fail):
        resp = h.handler(_event("GET /api/breakdown"), context=None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    # All four keys present, all >= 0; one hour silently skipped
    assert set(body.keys()) == {"brute_force", "credential_stuffing", "scanner", "other"}


# ------------------------------------------------------------- summary 2-getitem


@mock_aws
def test_summary_only_two_getitems():
    """The fix: /api/summary issues exactly TWO GetItems and zero Queries."""
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(ddb)
    table = boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE)
    h = _import_handler()
    today = h._now_utc().date().isoformat()
    table.put_item(
        Item={
            "pk": "SUMMARY#DAY",
            "sk": today,
            "type": "SUMMARY",
            "day": today,
            "total_events": 4321,
            "unique_ips": 99,
            "unique_sessions": 100,
            "successful_logins": 0,
            "file_downloads": 0,
            "techniques": {},
            "ttl": 9_999_999_999,
        }
    )
    table.put_item(
        Item={
            "pk": "HEARTBEAT",
            "sk": "honeypot",
            "last_event_ts": "2026-04-29T12:00:00Z",
        }
    )

    get_count = {"n": 0}
    query_count = {"n": 0}
    real_get = table.get_item
    real_query = table.query

    def counted_get(*args, **kwargs):
        get_count["n"] += 1
        return real_get(*args, **kwargs)

    def counted_query(*args, **kwargs):
        query_count["n"] += 1
        return real_query(*args, **kwargs)

    with (
        patch.object(h._TABLE, "get_item", side_effect=counted_get),
        patch.object(h._TABLE, "query", side_effect=counted_query),
    ):
        resp = h.handler(_event("GET /api/summary"), context=None)

    assert resp["statusCode"] == 200
    assert get_count["n"] == 2, f"expected exactly 2 GetItems, got {get_count['n']}"
    assert query_count["n"] == 0, f"expected zero Queries, got {query_count['n']}"

    body = json.loads(resp["body"])
    assert body["total"] == 4321
    assert body["last_24h"] == 4321
    assert body["last_1h"] == 0
    assert body["unique_ips_24h"] == 99
    assert body["sensor_last_seen"] == "2026-04-29T12:00:00Z"


@mock_aws
def test_summary_handles_missing_summary_day():
    """If today's SUMMARY#DAY hasn't been written yet, return zeros."""
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(ddb)
    h = _import_handler()
    resp = h.handler(_event("GET /api/summary"), context=None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["total"] == 0
    assert body["last_24h"] == 0
    assert body["last_1h"] == 0
    assert body["unique_ips_24h"] == 0
    assert body["sensor_last_seen"] is None


# ------------------------------------------------------------- real-IO parallel


@mock_aws
def test_timeline_real_concurrent_io_correctness():
    """Regression guard: 24 parallel queries through the executor + the
    low-level Client must all return correct results against moto-mocked
    DDB. Catches a future regression where someone swaps the parallel
    path back to the Resource interface and silently re-introduces the
    'parallel-but-actually-sequential' bug."""
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(ddb)
    table = boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE)
    h = _import_handler()

    # Seed AGG#HOUR# eventid counters for all 24 buckets so each parallel
    # query has actual data to read.
    now = h._now_utc()
    for offset in range(24):
        bucket_dt = now - __import__("datetime").timedelta(hours=offset)
        bucket = bucket_dt.strftime("%Y-%m-%dT%H")
        table.put_item(
            Item={
                "pk": f"AGG#HOUR#{bucket}#eventid",
                "sk": "VALUE#cowrie.login.failed",
                "type": "AGG_COUNT",
                "dimension": "eventid",
                "value": "cowrie.login.failed",
                "bucket": bucket,
                "count": 100 + offset,  # distinguishable per bucket
                "ttl": 9_999_999_999,
            }
        )

    resp = h.handler(_event("GET /api/timeline"), context=None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert len(body["buckets"]) == 24
    counts = [b["count"] for b in body["buckets"]]
    # Set equality — order-independent — sum should match the seed pattern
    assert sum(counts) == sum(100 + offset for offset in range(24))


@mock_aws
def test_breakdown_real_concurrent_io_correctness():
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(ddb)
    table = boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE)
    h = _import_handler()

    now = h._now_utc()
    for offset in range(24):
        bucket_dt = now - __import__("datetime").timedelta(hours=offset)
        bucket = bucket_dt.strftime("%Y-%m-%dT%H")
        for tech, count in [
            ("brute_force", 10 + offset),
            ("scanner", 1 + offset // 2),
        ]:
            table.put_item(
                Item={
                    "pk": f"AGG#HOUR#{bucket}#technique",
                    "sk": f"VALUE#{tech}",
                    "type": "AGG_COUNT",
                    "dimension": "technique",
                    "value": tech,
                    "bucket": bucket,
                    "count": count,
                    "ttl": 9_999_999_999,
                }
            )

    resp = h.handler(_event("GET /api/breakdown"), context=None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    expected_brute = sum(10 + offset for offset in range(24))
    expected_scanner = sum(1 + offset // 2 for offset in range(24))
    assert body["brute_force"] == expected_brute
    assert body["scanner"] == expected_scanner
    assert body["credential_stuffing"] == 0
    assert body["other"] == 0


@mock_aws
def test_client_query_paginate_unmarshals_correctly():
    """Direct test of the low-level Client paginated query with unmarshalling."""
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(ddb)
    table = boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE)
    h = _import_handler()

    pk_value = "AGG#HOUR#2026-04-29T00#username"
    for i in range(3):
        table.put_item(
            Item={
                "pk": pk_value,
                "sk": f"VALUE#user{i}",
                "type": "AGG_COUNT",
                "dimension": "username",
                "value": f"user{i}",
                "count": 10 * (i + 1),
                "ttl": 9_999_999_999,
            }
        )
    items = h._client_query_paginate(pk_value)
    assert len(items) == 3
    # All values are plain Python (not DDB attribute-value dicts)
    for it in items:
        assert isinstance(it["count"], int)
        assert it["pk"] == pk_value
    counts = sorted(it["count"] for it in items)
    assert counts == [10, 20, 30]


@mock_aws
def test_client_get_item_returns_none_on_miss():
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(ddb)
    h = _import_handler()
    out = h._client_get_item("SUMMARY#DAY", "1900-01-01")
    assert out is None
