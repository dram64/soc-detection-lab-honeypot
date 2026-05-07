"""moto-backed integration tests for the aggregator Lambda.

Covers the three dispatch paths:
  - DynamoDB Streams record processing
  - EventBridge {"action": "rank_rebuild"}
  - EventBridge {"action": "daily_summary"}
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from importlib import reload

import boto3
import pytest
from boto3.dynamodb.conditions import Key
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
                "IndexName": "gsi1",
                "KeySchema": [
                    {"AttributeName": "gsi1pk", "KeyType": "HASH"},
                    {"AttributeName": "gsi1sk", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
            {
                "IndexName": "gsi2",
                "KeySchema": [
                    {"AttributeName": "gsi2pk", "KeyType": "HASH"},
                    {"AttributeName": "gsi2sk", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
            {
                "IndexName": "gsi3",
                "KeySchema": [
                    {"AttributeName": "gsi3pk", "KeyType": "HASH"},
                    {"AttributeName": "gsi3sk", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
    )


def _import_aggregator():
    import functions.aggregator.handler as h
    return reload(h)


_EVENT_ID_COUNTER = [0]


def _stream_record(item: dict, *, event_name: str = "INSERT") -> dict:
    """Build a minimal DynamoDB Streams record carrying `item` as NewImage.

    Each call returns a record with a unique eventID so existing tests
    that build a payload of N records measure N distinct stream records
    (the dedup mechanism in Fix E would otherwise collapse them to one).
    """
    def _av(value):
        if value is None:
            return {"NULL": True}
        if isinstance(value, bool):
            return {"BOOL": value}
        if isinstance(value, int):
            return {"N": str(value)}
        if isinstance(value, float):
            return {"N": repr(value)}
        if isinstance(value, str):
            return {"S": value}
        raise TypeError(type(value))

    _EVENT_ID_COUNTER[0] += 1
    return {
        "eventID": f"shard-test:seq-{_EVENT_ID_COUNTER[0]:09d}",
        "eventName": event_name,
        "eventSource": "aws:dynamodb",
        "dynamodb": {
            "NewImage": {k: _av(v) for k, v in item.items()},
        },
    }


def _stream_payload(items: list[dict]) -> dict:
    return {"Records": [_stream_record(it) for it in items]}


def _put_event(table, *, ts: str, session: str, eventid: str, src_ip: str = "192.0.2.5", **extra):
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
        **extra,
    }
    table.put_item(Item=item)
    return item


# ---------------------------------------------------------------------------
# Stream-record path
# ---------------------------------------------------------------------------


@mock_aws
def test_stream_record_increments_per_dimension_counters():
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(ddb)
    h = _import_aggregator()

    item = {
        "pk": "SESSION#sess1",
        "sk": "2026-04-28T14:05:00.000000Z#cowrie.login.failed",
        "type": "EVENT",
        "ts": "2026-04-28T14:05:00.000000Z",
        "eventid": "cowrie.login.failed",
        "session": "sess1",
        "src_ip": "203.0.113.5",
        "sensor": "honeypot",
        "username": "root",
        "password": "123456",
        "country": "DE",
        "asn": 24940,
    }

    h.handler(_stream_payload([item]), context=None)

    table = boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE)
    bucket = "2026-04-28T14"
    for dim, value in [
        ("username", "root"),
        ("password", "123456"),
        ("country", "DE"),
        ("asn", "24940"),
        ("eventid", "cowrie.login.failed"),
    ]:
        resp = table.get_item(Key={"pk": f"AGG#HOUR#{bucket}#{dim}", "sk": f"VALUE#{value}"})
        assert resp.get("Item") is not None, f"missing counter for {dim}={value}"
        assert int(resp["Item"]["count"]) == 1


@mock_aws
def test_stream_records_atomically_accumulate_across_invocations():
    """50 records hitting overlapping dimensions must produce exact totals."""
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(ddb)
    h = _import_aggregator()

    base_item = {
        "pk": "SESSION#sess1",
        "sk": "...",
        "type": "EVENT",
        "ts": "2026-04-28T14:05:00.000000Z",
        "eventid": "cowrie.login.failed",
        "session": "sess1",
        "src_ip": "203.0.113.5",
        "sensor": "honeypot",
        "username": "root",
        "password": "123456",
        "country": "DE",
        "asn": 24940,
    }

    # Two separate Lambda invocations of 25 records each — the same as
    # serial Streams shard delivery in production.
    h.handler(_stream_payload([base_item] * 25), context=None)
    h.handler(_stream_payload([base_item] * 25), context=None)

    table = boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE)
    resp = table.get_item(Key={"pk": "AGG#HOUR#2026-04-28T14#username", "sk": "VALUE#root"})
    assert int(resp["Item"]["count"]) == 50


@mock_aws
def test_aggregator_skips_non_event_items():
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(ddb)
    h = _import_aggregator()

    rank_item = {
        "pk": "RANK#24H#username",
        "sk": "0000000142#root",
        "type": "RANK",
        "ts": "2026-04-28T14:05:00.000000Z",
        "eventid": "n/a",
        "session": "n/a",
        "sensor": "n/a",
        "src_ip": "0.0.0.0",
        "username": "root",
    }

    result = h.handler(_stream_payload([rank_item]), context=None)
    assert result.get("skipped_non_event") == 1
    assert result.get("processed", 0) == 0


@mock_aws
def test_session_closed_classifies_brute_force():
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(ddb)
    h = _import_aggregator()
    table = boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE)

    # Seed a brute-force-shaped session (1 username, 6 failed logins, then closed).
    base_ts = "2026-04-28T14:00:"
    for i in range(6):
        ts = f"{base_ts}{i:02d}.000000Z"
        _put_event(
            table,
            ts=ts,
            session="bf1",
            eventid="cowrie.login.failed",
            src_ip="203.0.113.5",
            username="root",
            password="123456",
        )
    closed = {
        "pk": "SESSION#bf1",
        "sk": f"{base_ts}10.000000Z#cowrie.session.closed",
        "type": "EVENT",
        "ts": f"{base_ts}10.000000Z",
        "eventid": "cowrie.session.closed",
        "session": "bf1",
        "src_ip": "203.0.113.5",
        "sensor": "honeypot",
        "duration": Decimal("30.0"),
    }
    table.put_item(Item=closed)
    # Stream record carries duration as float (matches the wire format).
    h.handler(_stream_payload([{**closed, "duration": 30.0}]), context=None)

    technique_resp = table.get_item(
        Key={"pk": "AGG#HOUR#2026-04-28T14#technique", "sk": "VALUE#brute_force"}
    )
    assert technique_resp.get("Item") is not None
    assert int(technique_resp["Item"]["count"]) == 1


# ---------------------------------------------------------------------------
# Rank rebuild
# ---------------------------------------------------------------------------


@mock_aws
def test_rank_rebuild_emits_descending_top_n():
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(ddb)
    h = _import_aggregator()
    table = boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE)

    fixed_now = datetime(2026, 4, 28, 14, 30, tzinfo=timezone.utc)
    bucket = fixed_now.strftime("%Y-%m-%dT%H")

    # Seed AGG#HOUR# counters for 30 distinct usernames at varying counts.
    counts = {f"user{i:02d}": 100 - i for i in range(30)}
    with table.batch_writer() as bw:
        for user, count in counts.items():
            bw.put_item(
                Item={
                    "pk": f"AGG#HOUR#{bucket}#username",
                    "sk": f"VALUE#{user}",
                    "type": "AGG_COUNT",
                    "dimension": "username",
                    "value": user,
                    "bucket": bucket,
                    "count": count,
                    "ttl": 9_999_999_999,
                }
            )

    result = h._handle_rank_rebuild(now=fixed_now)
    assert result["24H#username"] == 25  # RANK_TOP_N

    # Read back via GSI3 — the lowest-sk-first row should be the top user (user00, count 100).
    resp = table.query(
        IndexName="gsi3",
        KeyConditionExpression=Key("gsi3pk").eq("RANK#24H#username"),
        Limit=1,
    )
    assert len(resp["Items"]) == 1
    top = resp["Items"][0]
    assert top["value"] == "user00"
    assert int(top["count"]) == 100


@mock_aws
def test_rank_rebuild_no_duplicates_when_counts_change():
    """Property test for the delete-then-write fix.

    Step 1: seed 30 distinct values.
    Step 2: rebuild → expect exactly RANK_TOP_N items.
    Step 3: bump one value's count so its sk would change.
    Step 4: rebuild again → still exactly RANK_TOP_N items, no value duplicated.
    """
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(ddb)
    h = _import_aggregator()
    table = boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE)

    fixed_now = datetime(2026, 4, 28, 14, 30, tzinfo=timezone.utc)
    bucket = fixed_now.strftime("%Y-%m-%dT%H")

    def _seed_counter(value: str, count: int) -> None:
        table.put_item(
            Item={
                "pk": f"AGG#HOUR#{bucket}#username",
                "sk": f"VALUE#{value}",
                "type": "AGG_COUNT",
                "dimension": "username",
                "value": value,
                "bucket": bucket,
                "count": count,
                "ttl": 9_999_999_999,
            }
        )

    for i in range(30):
        _seed_counter(f"user{i:02d}", 100 - i)

    h._handle_rank_rebuild(now=fixed_now)
    rank_resp = table.query(
        KeyConditionExpression=Key("pk").eq("RANK#24H#username"),
    )
    assert rank_resp["Count"] == 25

    # Bump user05 from 95 to 250 — its sk changes.
    _seed_counter("user05", 250)

    h._handle_rank_rebuild(now=fixed_now)
    rank_resp_2 = table.query(
        KeyConditionExpression=Key("pk").eq("RANK#24H#username"),
    )
    assert rank_resp_2["Count"] == 25, (
        f"expected 25 rank items, got {rank_resp_2['Count']} — duplicates leaked"
    )

    # No value appears twice.
    values = [it["value"] for it in rank_resp_2["Items"]]
    assert len(values) == len(set(values)), f"duplicate value(s): {values}"

    # user05 is now top by count.
    user05_items = [it for it in rank_resp_2["Items"] if it["value"] == "user05"]
    assert len(user05_items) == 1
    assert int(user05_items[0]["count"]) == 250


@mock_aws
def test_rank_rebuild_handles_dimension_with_few_values():
    """Edge case: fewer than RANK_TOP_N unique values; old rows still cleared."""
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(ddb)
    h = _import_aggregator()
    table = boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE)

    fixed_now = datetime(2026, 4, 28, 14, 30, tzinfo=timezone.utc)
    bucket = fixed_now.strftime("%Y-%m-%dT%H")

    # Seed only 3 values, then rebuild.
    for i, count in enumerate([100, 50, 25]):
        table.put_item(
            Item={
                "pk": f"AGG#HOUR#{bucket}#username",
                "sk": f"VALUE#user{i}",
                "type": "AGG_COUNT",
                "dimension": "username",
                "value": f"user{i}",
                "bucket": bucket,
                "count": count,
                "ttl": 9_999_999_999,
            }
        )
    h._handle_rank_rebuild(now=fixed_now)
    assert table.query(KeyConditionExpression=Key("pk").eq("RANK#24H#username"))["Count"] == 3

    # Drop user2 entirely (delete its counter), bump user1.
    table.delete_item(Key={
        "pk": f"AGG#HOUR#{bucket}#username",
        "sk": "VALUE#user2",
    })
    table.update_item(
        Key={"pk": f"AGG#HOUR#{bucket}#username", "sk": "VALUE#user1"},
        UpdateExpression="SET #c = :c",
        ExpressionAttributeNames={"#c": "count"},
        ExpressionAttributeValues={":c": 200},
    )

    h._handle_rank_rebuild(now=fixed_now)
    rebuilt = table.query(KeyConditionExpression=Key("pk").eq("RANK#24H#username"))
    # Now exactly 2 items, user2 is gone, user1 is top.
    assert rebuilt["Count"] == 2
    values = sorted(it["value"] for it in rebuilt["Items"])
    assert values == ["user0", "user1"]


@mock_aws
def test_rank_rebuild_idempotent():
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(ddb)
    h = _import_aggregator()
    table = boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE)

    fixed_now = datetime(2026, 4, 28, 14, 30, tzinfo=timezone.utc)
    bucket = fixed_now.strftime("%Y-%m-%dT%H")
    table.put_item(
        Item={
            "pk": f"AGG#HOUR#{bucket}#username",
            "sk": "VALUE#root",
            "type": "AGG_COUNT",
            "dimension": "username",
            "value": "root",
            "bucket": bucket,
            "count": 142,
            "ttl": 9_999_999_999,
        }
    )

    h._handle_rank_rebuild(now=fixed_now)
    h._handle_rank_rebuild(now=fixed_now)

    resp = table.query(
        IndexName="gsi3",
        KeyConditionExpression=Key("gsi3pk").eq("RANK#24H#username"),
    )
    assert len(resp["Items"]) == 1
    assert int(resp["Items"][0]["count"]) == 142


@mock_aws
def test_rank_dispatch_via_handler_action():
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(ddb)
    h = _import_aggregator()
    # No counters seeded; rank rebuild should produce 0 items per (window, dim).
    result = h.handler({"action": "rank_rebuild"}, context=None)
    for window in ("24H", "7D"):
        for dim in ("username", "password", "country", "asn", "technique"):
            assert result[f"{window}#{dim}"] == 0


# ---------------------------------------------------------------------------
# Daily summary
# ---------------------------------------------------------------------------


@mock_aws
def test_daily_summary_aggregates_yesterday():
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(ddb)
    h = _import_aggregator()
    table = boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE)

    fixed_now = datetime(2026, 4, 29, 0, 5, tzinfo=timezone.utc)
    yesterday = "2026-04-28"

    _put_event(
        table,
        ts=f"{yesterday}T14:00:00.000000Z",
        session="s1",
        eventid="cowrie.login.failed",
        src_ip="203.0.113.5",
    )
    _put_event(
        table,
        ts=f"{yesterday}T14:00:01.000000Z",
        session="s1",
        eventid="cowrie.login.success",
        src_ip="203.0.113.5",
    )
    _put_event(
        table,
        ts=f"{yesterday}T15:00:00.000000Z",
        session="s2",
        eventid="cowrie.session.file_download",
        src_ip="203.0.113.6",
        url="http://x/bot.sh",
        shasum="ab",
    )
    # technique counter for yesterday
    table.put_item(
        Item={
            "pk": f"AGG#HOUR#{yesterday}T14#technique",
            "sk": "VALUE#brute_force",
            "type": "AGG_COUNT",
            "dimension": "technique",
            "value": "brute_force",
            "bucket": f"{yesterday}T14",
            "count": 7,
            "ttl": 9_999_999_999,
        }
    )

    item = h._handle_daily_summary(now=fixed_now)
    assert item["day"] == yesterday
    assert item["total_events"] == 3
    assert item["unique_sessions"] == 2
    assert item["unique_ips"] == 2
    assert item["successful_logins"] == 1
    assert item["file_downloads"] == 1
    assert item["techniques"] == {"brute_force": 7}


@mock_aws
def test_daily_summary_dispatch_via_handler_action():
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(ddb)
    h = _import_aggregator()
    # No yesterday data — handler should still write a zero summary for the day.
    result = h.handler({"action": "daily_summary"}, context=None)
    assert "day" in result
    assert result["total_events"] == 0


@mock_aws
def test_today_summary_aggregates_today_not_yesterday():
    """Phase 10 BUG 1 follow-up. The 5-min cron writes today's
    SUMMARY#DAY (not yesterday's) so /api/summary returns near-real-
    time totals."""
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(ddb)
    h = _import_aggregator()
    table = boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE)

    fixed_now = datetime(2026, 5, 7, 12, 30, tzinfo=timezone.utc)
    today = "2026-05-07"
    yesterday = "2026-05-06"

    _put_event(
        table,
        ts=f"{today}T05:00:00.000000Z",
        session="t1",
        eventid="cowrie.login.failed",
        src_ip="198.51.100.1",
    )
    _put_event(
        table,
        ts=f"{today}T11:00:00.000000Z",
        session="t2",
        eventid="cowrie.session.connect",
        src_ip="203.0.113.42",
    )
    # Yesterday data exists too — must NOT count toward today's rollup.
    _put_event(
        table,
        ts=f"{yesterday}T14:00:00.000000Z",
        session="y1",
        eventid="cowrie.login.failed",
        src_ip="192.0.2.99",
    )

    item = h._handle_daily_summary(now=fixed_now, target="today")
    assert item["day"] == today
    assert item["total_events"] == 2
    assert item["unique_sessions"] == 2
    assert item["unique_ips"] == 2


@mock_aws
def test_today_summary_dispatch_via_handler_action():
    """The new today_summary action triggers _handle_daily_summary
    with target='today' and writes today's SUMMARY#DAY row."""
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(ddb)
    h = _import_aggregator()
    result = h.handler({"action": "today_summary"}, context=None)
    today_iso = h._now_utc().date().isoformat()
    assert result["day"] == today_iso


@mock_aws
def test_unknown_action_is_noop():
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(ddb)
    h = _import_aggregator()
    result = h.handler({"action": "wat"}, context=None)
    assert result == {"status": "no-op"}


# ---------------------------------------------------------------------------
# Fix E — eventID-based dedup
# ---------------------------------------------------------------------------


def _record_with_event_id(event_id: str, item: dict) -> dict:
    rec = _stream_record(item)
    rec["eventID"] = event_id
    return rec


@mock_aws
def test_same_event_id_replay_does_not_double_count():
    """Fix E core property: a stream record with the same eventID, replayed,
    must increment the counter exactly once."""
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(ddb)
    h = _import_aggregator()
    table = boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE)

    item = {
        "pk": "SESSION#dup1",
        "sk": "2026-04-28T14:05:00.000000Z#cowrie.login.failed",
        "type": "EVENT",
        "ts": "2026-04-28T14:05:00.000000Z",
        "eventid": "cowrie.login.failed",
        "session": "dup1",
        "src_ip": "203.0.113.5",
        "sensor": "honeypot",
        "username": "root",
    }
    record = _record_with_event_id("shard-1:seq-100", item)
    payload = {"Records": [record]}

    h.handler(payload, context=None)
    h.handler(payload, context=None)  # replay
    h.handler(payload, context=None)  # replay again

    counter = table.get_item(
        Key={"pk": "AGG#HOUR#2026-04-28T14#username", "sk": "VALUE#root"}
    )["Item"]
    assert int(counter["count"]) == 1, (
        f"expected count=1 after 3 replays of same eventID; got {counter['count']}"
    )


@mock_aws
def test_dedup_sentinel_written_with_ttl():
    """The sentinel item must be written with `ttl` set to ~now + 1h."""
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(ddb)
    h = _import_aggregator()
    table = boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE)

    item = {
        "pk": "SESSION#ttl1",
        "sk": "2026-04-28T14:05:00.000000Z#cowrie.session.connect",
        "type": "EVENT",
        "ts": "2026-04-28T14:05:00.000000Z",
        "eventid": "cowrie.session.connect",
        "session": "ttl1",
        "src_ip": "203.0.113.5",
        "sensor": "honeypot",
    }
    h.handler({"Records": [_record_with_event_id("shard-1:seq-200", item)]}, context=None)

    sentinel = table.get_item(Key={"pk": "DEDUP#STREAM", "sk": "shard-1:seq-200"})
    assert sentinel.get("Item") is not None
    assert sentinel["Item"]["type"] == "DEDUP_SENTINEL"

    import time as _time
    now = int(_time.time())
    ttl = int(sentinel["Item"]["ttl"])
    # TTL = +1h ± a few seconds of test runtime
    assert 3500 <= (ttl - now) <= 3700, f"ttl delta {ttl - now} outside 1h window"


@mock_aws
def test_dedup_miss_path_increments_normally():
    """Distinct eventIDs each go through; counters accumulate."""
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(ddb)
    h = _import_aggregator()
    table = boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE)

    base = {
        "pk": "SESSION#fresh",
        "sk": "2026-04-28T14:05:00.000000Z#cowrie.login.failed",
        "type": "EVENT",
        "ts": "2026-04-28T14:05:00.000000Z",
        "eventid": "cowrie.login.failed",
        "session": "fresh",
        "src_ip": "203.0.113.5",
        "sensor": "honeypot",
        "username": "root",
    }
    payload = {
        "Records": [
            _record_with_event_id("shard-1:seq-300", base),
            _record_with_event_id("shard-1:seq-301", base),
            _record_with_event_id("shard-1:seq-302", base),
        ]
    }
    h.handler(payload, context=None)

    counter = table.get_item(
        Key={"pk": "AGG#HOUR#2026-04-28T14#username", "sk": "VALUE#root"}
    )["Item"]
    assert int(counter["count"]) == 3


@mock_aws
def test_dedup_does_not_apply_to_eventbridge_actions():
    """EventBridge schedule payloads have no eventID and shouldn't be
    deduplicated. Two consecutive rank_rebuild invocations should both run."""
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(ddb)
    h = _import_aggregator()
    table = boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE)

    fixed_now = datetime(2026, 4, 28, 14, 30, tzinfo=timezone.utc)
    bucket = fixed_now.strftime("%Y-%m-%dT%H")
    table.put_item(
        Item={
            "pk": f"AGG#HOUR#{bucket}#username",
            "sk": "VALUE#root",
            "type": "AGG_COUNT",
            "dimension": "username",
            "value": "root",
            "bucket": bucket,
            "count": 5,
            "ttl": 9_999_999_999,
        }
    )

    # Both invocations should produce the same RANK#24H#username item state.
    h._handle_rank_rebuild(now=fixed_now)
    h._handle_rank_rebuild(now=fixed_now)

    rank = table.query(
        KeyConditionExpression=Key("pk").eq("RANK#24H#username"),
    )
    assert rank["Count"] == 1
    assert int(rank["Items"][0]["count"]) == 5
    # No dedup sentinels should have been written for the scheduled rebuilds.
    sentinels = table.query(
        KeyConditionExpression=Key("pk").eq("DEDUP#STREAM"),
    )
    assert sentinels["Count"] == 0


@mock_aws
def test_stream_record_without_event_id_processes_defensively():
    """A stream record missing the eventID field is still processed
    (defensive: prefer over-counting once than silently dropping)."""
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(ddb)
    h = _import_aggregator()
    table = boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE)

    item = {
        "pk": "SESSION#noid",
        "sk": "2026-04-28T14:05:00.000000Z#cowrie.login.failed",
        "type": "EVENT",
        "ts": "2026-04-28T14:05:00.000000Z",
        "eventid": "cowrie.login.failed",
        "session": "noid",
        "src_ip": "203.0.113.5",
        "sensor": "honeypot",
        "username": "root",
    }
    rec = _stream_record(item)
    rec.pop("eventID", None)
    h.handler({"Records": [rec]}, context=None)

    counter = table.get_item(
        Key={"pk": "AGG#HOUR#2026-04-28T14#username", "sk": "VALUE#root"}
    )["Item"]
    assert int(counter["count"]) == 1


@mock_aws
def test_stream_record_without_new_image_skipped():
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(ddb)
    h = _import_aggregator()
    payload = {
        "Records": [
            {
                "eventID": "1",
                "eventName": "INSERT",
                "eventSource": "aws:dynamodb",
                "dynamodb": {},
            }
        ]
    }
    result = h.handler(payload, context=None)
    assert result.get("skipped") == 1


@mock_aws
def test_stream_remove_event_skipped():
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(ddb)
    h = _import_aggregator()
    item = {
        "pk": "SESSION#x",
        "sk": "ts#cowrie.session.connect",
        "type": "EVENT",
        "ts": "2026-04-28T14:00:00.000000Z",
        "eventid": "cowrie.session.connect",
        "session": "x",
        "src_ip": "203.0.113.5",
        "sensor": "honeypot",
    }
    payload = _stream_payload([item])
    payload["Records"][0]["eventName"] = "REMOVE"
    result = h.handler(payload, context=None)
    assert result.get("skipped") == 1


@mock_aws
def test_session_closed_without_session_id_skips_classification():
    """Defensive: if a malformed session.closed lacks the session field,
    classification returns None; no technique counter is written."""
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(ddb)
    h = _import_aggregator()
    table = boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE)

    closed_no_session = {
        "type": "EVENT",
        "ts": "2026-04-28T14:00:00.000000Z",
        "eventid": "cowrie.session.closed",
        "session": "",  # empty → classifier returns None
        "src_ip": "203.0.113.5",
        "sensor": "honeypot",
        "duration": 30.0,
    }
    h.handler(_stream_payload([closed_no_session]), context=None)

    # No technique counter should exist.
    resp = table.query(KeyConditionExpression=Key("pk").eq("AGG#HOUR#2026-04-28T14#technique"))
    assert resp.get("Items", []) == []


@mock_aws
def test_rank_rebuild_skips_buckets_with_no_value_attribute():
    """Defensive: if an AGG#HOUR# row is missing the `value` attribute,
    it's skipped rather than crashing the rank rebuild."""
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _create_table(ddb)
    h = _import_aggregator()
    table = boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE)

    fixed_now = datetime(2026, 4, 28, 14, 30, tzinfo=timezone.utc)
    bucket = fixed_now.strftime("%Y-%m-%dT%H")
    # One valid + one corrupt counter.
    table.put_item(
        Item={
            "pk": f"AGG#HOUR#{bucket}#username",
            "sk": "VALUE#root",
            "type": "AGG_COUNT",
            "value": "root",
            "count": 5,
        }
    )
    table.put_item(
        Item={
            "pk": f"AGG#HOUR#{bucket}#username",
            "sk": "VALUE#corrupt",
            "type": "AGG_COUNT",
            # value attribute deliberately missing
            "count": 99,
        }
    )

    out = h._handle_rank_rebuild(now=fixed_now)
    assert out["24H#username"] == 1  # only the valid one ranked
