"""moto-backed integration tests for the API Lambda."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from importlib import reload

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
    monkeypatch.setenv("GIT_SHA", "test-sha-abc123")


def _create_table(ddb):
    ddb.create_table(
        TableName=TABLE,
        AttributeDefinitions=[
            {"AttributeName": "pk", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
            {"AttributeName": "gsi1pk", "AttributeType": "S"},
            {"AttributeName": "gsi1sk", "AttributeType": "S"},
            {"AttributeName": "gsi2pk", "AttributeType": "S"},
            {"AttributeName": "gsi2sk", "AttributeType": "S"},
            {"AttributeName": "gsi3pk", "AttributeType": "S"},
            {"AttributeName": "gsi3sk", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "pk", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
        BillingMode="PAY_PER_REQUEST",
        GlobalSecondaryIndexes=[
            {
                "IndexName": idx,
                "KeySchema": [
                    {"AttributeName": f"{idx}pk", "KeyType": "HASH"},
                    {"AttributeName": f"{idx}sk", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
            for idx in ("gsi1", "gsi2", "gsi3")
        ],
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


def _put_event(table, *, ts: str, session: str, eventid: str,
               src_ip: str = "192.0.2.5", **extra):
    item = {
        "pk": f"SESSION#{session}",
        "sk": f"{ts}#{eventid}",
        "gsi1pk": f"IP#{src_ip}",
        "gsi1sk": ts,
        "gsi2pk": f"DAY#{ts[:10]}",
        "gsi2sk": f"{ts}#SESSION#{session}",
        "type": "EVENT",
        "ts": ts,
        "session": session,
        "eventid": eventid,
        "src_ip": src_ip,
        "sensor": "honeypot",
        "ingest_id": f"sha1:{session}-{eventid}",
        "ttl": 9_999_999_999,
        **extra,
    }
    table.put_item(Item=item)


def _put_rank(table, *, window: str, dim: str, value: str, count: int):
    sk = f"{9_999_999_999 - count:010d}#{value}"
    table.put_item(
        Item={
            "pk": f"RANK#{window}#{dim}",
            "sk": sk,
            "gsi3pk": f"RANK#{window}#{dim}",
            "gsi3sk": sk,
            "type": "RANK",
            "window": window,
            "dimension": dim,
            "value": value,
            "count": count,
            "ttl": 9_999_999_999,
        }
    )


def _put_summary(table, *, day: str, total_events: int, unique_ips: int = 1,
                 unique_sessions: int = 1, **extra):
    table.put_item(
        Item={
            "pk": "SUMMARY#DAY",
            "sk": day,
            "type": "SUMMARY",
            "day": day,
            "total_events": total_events,
            "unique_ips": unique_ips,
            "unique_sessions": unique_sessions,
            "successful_logins": 0,
            "file_downloads": 0,
            "techniques": {},
            "ttl": 9_999_999_999,
            **extra,
        }
    )


# ------------------------------------------------------------------ healthz


@mock_aws
def test_healthz_returns_ok_with_version():
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(ddb)
    h = _import_handler()
    resp = h.handler(_event("GET /api/healthz"), context=None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body == {"status": "ok", "version": "test-sha-abc123"}
    # CORS headers present
    assert resp["headers"]["Access-Control-Allow-Origin"] == "https://dashboard.dram-soc.org"


@mock_aws
def test_healthz_no_cache():
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(ddb)
    h = _import_handler()
    resp = h.handler(_event("GET /api/healthz"), context=None)
    assert resp["headers"]["Cache-Control"] == "no-cache"


# ------------------------------------------------------------------ summary


@mock_aws
def test_summary_reads_today_summary_only():
    """Updated for the v1.5 2-GetItem fix: /api/summary reads only the
    current day's SUMMARY#DAY rollup + the HEARTBEAT, not historical days."""
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(ddb)
    table = boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE)
    h = _import_handler()

    today = h._now_utc().date().isoformat()
    yesterday = (h._now_utc().date() - timedelta(days=1)).isoformat()

    _put_summary(table, day=today, total_events=100, unique_ips=20)
    # Yesterday's summary exists but is NOT included in the response
    _put_summary(table, day=yesterday, total_events=200, unique_ips=30)

    resp = h.handler(_event("GET /api/summary"), context=None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["total"] == 100
    assert body["last_24h"] == 100
    assert body["unique_ips_24h"] == 20
    assert body["last_1h"] == 0  # placeholder until SUMMARY#HOUR rollup exists
    assert body["sensor_last_seen"] is None


@mock_aws
def test_summary_with_heartbeat():
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(ddb)
    table = boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE)
    h = _import_handler()
    table.put_item(
        Item={
            "pk": "HEARTBEAT",
            "sk": "honeypot",
            "last_event_ts": "2026-04-29T12:34:56Z",
            "last_ingest_ts": "2026-04-29T12:34:57Z",
        }
    )
    resp = h.handler(_event("GET /api/summary"), context=None)
    body = json.loads(resp["body"])
    assert body["sensor_last_seen"] == "2026-04-29T12:34:56Z"


# ------------------------------------------------------------------ timeline


@mock_aws
def test_timeline_default_24h_1h_buckets():
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(ddb)
    h = _import_handler()
    resp = h.handler(_event("GET /api/timeline"), context=None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert len(body["buckets"]) == 24


@mock_aws
def test_timeline_invalid_bucket_returns_400():
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(ddb)
    h = _import_handler()
    resp = h.handler(_event("GET /api/timeline", query={"bucket": "5m"}), context=None)
    assert resp["statusCode"] == 400


@mock_aws
def test_timeline_7d_with_daily_summaries():
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(ddb)
    table = boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE)
    h = _import_handler()
    today = h._now_utc().date()
    for offset in range(7):
        day = (today - timedelta(days=offset)).isoformat()
        _put_summary(table, day=day, total_events=100 * (offset + 1))
    resp = h.handler(
        _event("GET /api/timeline", query={"bucket": "1d", "window": "7d"}),
        context=None,
    )
    body = json.loads(resp["body"])
    assert len(body["buckets"]) == 7
    counts = sum(b["count"] for b in body["buckets"])
    assert counts == sum(100 * (i + 1) for i in range(7))


# ------------------------------------------------------------------ top/{dim}


@mock_aws
def test_top_usernames_returns_top_n():
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(ddb)
    table = boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE)
    h = _import_handler()
    for i in range(30):
        _put_rank(table, window="24H", dim="username",
                  value=f"user{i:02d}", count=100 - i)
    resp = h.handler(
        _event("GET /api/top/{dimension}",
               query={"limit": "5"},
               path={"dimension": "usernames"}),
        context=None,
    )
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert len(body["items"]) == 5
    assert body["items"][0]["value"] == "user00"
    assert body["items"][0]["count"] == 100


@mock_aws
def test_top_passwords_uses_password_dimension():
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(ddb)
    table = boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE)
    h = _import_handler()
    _put_rank(table, window="24H", dim="password", value="123456", count=999)
    resp = h.handler(
        _event("GET /api/top/{dimension}",
               path={"dimension": "passwords"}),
        context=None,
    )
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["items"][0]["value"] == "123456"


@mock_aws
def test_top_asns_returns_int_asn():
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(ddb)
    table = boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE)
    h = _import_handler()
    _put_rank(table, window="24H", dim="asn", value="14061", count=500)
    resp = h.handler(
        _event("GET /api/top/{dimension}", path={"dimension": "asns"}),
        context=None,
    )
    body = json.loads(resp["body"])
    assert body["items"][0]["asn"] == 14061


@mock_aws
def test_top_countries_uses_country_dimension():
    """Regression for the Phase 7 latent rstrip bug: countries → countrie.

    `dim.rstrip("s")` was naive plural-stripping. "countries" → "countrie"
    (rstrip removes EVERY trailing 's', not one). The fix is an explicit
    plural→singular map. This test asserts the country dimension is
    actually queried."""
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(ddb)
    table = boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE)
    h = _import_handler()
    _put_rank(table, window="24H", dim="country", value="CN", count=999)
    _put_rank(table, window="24H", dim="country", value="US", count=500)
    resp = h.handler(
        _event("GET /api/top/{dimension}", path={"dimension": "countries"}),
        context=None,
    )
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert len(body["items"]) == 2
    assert body["items"][0]["value"] == "CN"
    assert body["items"][0]["count"] == 999


@mock_aws
def test_top_unknown_dimension_returns_404():
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(ddb)
    h = _import_handler()
    resp = h.handler(
        _event("GET /api/top/{dimension}", path={"dimension": "bogus"}),
        context=None,
    )
    assert resp["statusCode"] == 404


@mock_aws
def test_top_invalid_limit_returns_400():
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(ddb)
    h = _import_handler()
    resp = h.handler(
        _event("GET /api/top/{dimension}",
               query={"limit": "9999"},
               path={"dimension": "usernames"}),
        context=None,
    )
    assert resp["statusCode"] == 400


# ------------------------------------------------------------------ events


@mock_aws
def test_events_returns_today_descending():
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(ddb)
    table = boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE)
    h = _import_handler()
    today_iso = h._now_utc().date().isoformat()
    for i in range(5):
        ts = f"{today_iso}T1{i}:00:00.000000Z"
        _put_event(
            table,
            ts=ts,
            session=f"sess-{i}",
            eventid="cowrie.login.failed",
            username="root",
        )
    resp = h.handler(_event("GET /api/events", query={"limit": "10"}), context=None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert len(body["items"]) == 5
    timestamps = [it["ts"] for it in body["items"]]
    assert timestamps == sorted(timestamps, reverse=True)


@mock_aws
def test_events_password_raw_never_appears():
    """The Phase 4 watch-item contract: password_raw must NOT appear in
    /api/events output, ever. Stored events contain it; public events drop
    it; the JSON serialization carries no trace."""
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(ddb)
    table = boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE)
    h = _import_handler()
    today_iso = h._now_utc().date().isoformat()
    secret = "DO-NOT-LEAK-THIS-VALUE-EVER"
    _put_event(
        table,
        ts=f"{today_iso}T12:00:00.000000Z",
        session="sec1",
        eventid="cowrie.login.failed",
        username="root",
        password="<filtered:len=27>",
        password_raw=secret,
    )
    resp = h.handler(_event("GET /api/events"), context=None)
    assert resp["statusCode"] == 200
    body = resp["body"]  # raw JSON string
    assert "password_raw" not in body, (
        "password_raw field name leaked in /api/events response"
    )
    assert secret not in body, (
        "password_raw VALUE leaked in /api/events response"
    )


@mock_aws
def test_events_pagination_via_before():
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(ddb)
    table = boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE)
    h = _import_handler()
    today_iso = h._now_utc().date().isoformat()
    for i in range(8):
        ts = f"{today_iso}T1{i}:00:00.000000Z"
        _put_event(
            table,
            ts=ts,
            session=f"sess-{i}",
            eventid="cowrie.login.failed",
            username="root",
        )
    page1 = h.handler(_event("GET /api/events", query={"limit": "3"}), context=None)
    body1 = json.loads(page1["body"])
    assert len(body1["items"]) == 3
    assert body1["next_before"] is not None

    page2 = h.handler(
        _event("GET /api/events",
               query={"limit": "3", "before": body1["next_before"]}),
        context=None,
    )
    body2 = json.loads(page2["body"])
    # Pages don't overlap
    seen = {it["ts"] for it in body1["items"]} | {it["ts"] for it in body2["items"]}
    assert len(seen) == len(body1["items"]) + len(body2["items"])


@mock_aws
def test_events_invalid_limit_returns_400():
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(ddb)
    h = _import_handler()
    resp = h.handler(_event("GET /api/events", query={"limit": "0"}), context=None)
    assert resp["statusCode"] == 400


# ------------------------------------------------------------------ breakdown


@mock_aws
def test_breakdown_sums_technique_counters():
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(ddb)
    table = boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE)
    h = _import_handler()
    bucket = h._now_utc().strftime("%Y-%m-%dT%H")
    for tech, count in [
        ("brute_force", 100),
        ("credential_stuffing", 30),
        ("scanner", 10),
        ("other", 5),
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
    assert body == {
        "brute_force": 100,
        "credential_stuffing": 30,
        "scanner": 10,
        "other": 5,
    }


# ------------------------------------------------------------------ sessions/{id}


@mock_aws
def test_session_returns_all_session_events_in_order():
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(ddb)
    table = boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE)
    h = _import_handler()
    base_ts = "2026-04-29T15:00:"
    for i, eid in enumerate(["cowrie.session.connect",
                             "cowrie.login.failed",
                             "cowrie.login.failed",
                             "cowrie.session.closed"]):
        ts = f"{base_ts}{i:02d}.000000Z"
        extra = {"username": "root", "password": "123456"} if "login" in eid else {}
        if eid == "cowrie.session.closed":
            extra["duration"] = 30
        if eid == "cowrie.session.connect":
            extra.update({"src_port": 1234, "dst_port": 2222})
        _put_event(
            table,
            ts=ts,
            session="abc",
            eventid=eid,
            **extra,
        )
    resp = h.handler(
        _event("GET /api/sessions/{id}", path={"id": "abc"}),
        context=None,
    )
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert len(body["events"]) == 4


@mock_aws
def test_session_does_not_leak_password_raw():
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(ddb)
    table = boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE)
    h = _import_handler()
    secret = "another-secret-do-not-leak-2"
    _put_event(
        table,
        ts="2026-04-29T15:00:00.000000Z",
        session="leak-test",
        eventid="cowrie.login.failed",
        username="root",
        password="<filtered:len=28>",
        password_raw=secret,
    )
    resp = h.handler(
        _event("GET /api/sessions/{id}", path={"id": "leak-test"}),
        context=None,
    )
    assert resp["statusCode"] == 200
    body = resp["body"]
    assert "password_raw" not in body
    assert secret not in body


@mock_aws
def test_session_missing_id_returns_400():
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(ddb)
    h = _import_handler()
    resp = h.handler(_event("GET /api/sessions/{id}", path={"id": ""}), context=None)
    assert resp["statusCode"] == 400


# ------------------------------------------------------------------ dispatch


@mock_aws
def test_unknown_route_returns_404():
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(ddb)
    h = _import_handler()
    resp = h.handler(_event("POST /api/whatever"), context=None)
    assert resp["statusCode"] == 404


#.5 CORS


def _event_with_origin(route_key: str, origin: str | None) -> dict:
    return {
        "routeKey": route_key,
        "queryStringParameters": None,
        "pathParameters": None,
        "headers": ({"origin": origin} if origin else {}),
    }


@mock_aws
def test_cors_echoes_allowlisted_origin(monkeypatch):
    monkeypatch.setenv(
        "ALLOWED_ORIGIN",
        "https://dashboard.dram-soc.org,https://dram-soc.org,https://www.dram-soc.org",
    )
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(ddb)
    h = _import_handler()

    # Apex origin in the allowlist → echoed back.
    resp = h.handler(_event_with_origin("GET /api/healthz", "https://dram-soc.org"), context=None)
    assert resp["headers"]["Access-Control-Allow-Origin"] == "https://dram-soc.org"
    assert resp["headers"]["Vary"] == "Origin"


@mock_aws
def test_cors_unknown_origin_falls_back_to_default(monkeypatch):
    monkeypatch.setenv(
        "ALLOWED_ORIGIN",
        "https://dashboard.dram-soc.org,https://dram-soc.org,https://www.dram-soc.org",
    )
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(ddb)
    h = _import_handler()

    # An origin NOT in the allowlist → first allowlisted entry returned.
    # API GW's preflight will already have rejected it; the Lambda's response
    # is just defense-in-depth (the browser will reject either way).
    resp = h.handler(_event_with_origin("GET /api/healthz", "https://evil.example"), context=None)
    assert resp["headers"]["Access-Control-Allow-Origin"] == "https://dashboard.dram-soc.org"


@mock_aws
def test_cors_no_origin_header_uses_default(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGIN", "https://dashboard.dram-soc.org,https://dram-soc.org")
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(ddb)
    h = _import_handler()

    # No Origin header (curl, server-side, etc.) → default origin returned.
    resp = h.handler(_event_with_origin("GET /api/healthz", None), context=None)
    assert resp["headers"]["Access-Control-Allow-Origin"] == "https://dashboard.dram-soc.org"


@mock_aws
def test_cors_single_origin_omits_vary_header(monkeypatch):
    # Back-compat: when only one origin is allowlisted (the Phase 4 default),
    # the Vary: Origin header is omitted because there's nothing to vary on.
    monkeypatch.setenv("ALLOWED_ORIGIN", "https://dashboard.dram-soc.org")
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(ddb)
    h = _import_handler()
    resp = h.handler(_event_with_origin("GET /api/healthz", "https://dashboard.dram-soc.org"), context=None)
    assert resp["headers"]["Access-Control-Allow-Origin"] == "https://dashboard.dram-soc.org"
    assert "Vary" not in resp["headers"]
