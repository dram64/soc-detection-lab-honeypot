from __future__ import annotations

import gzip
import json
from datetime import datetime, timezone
from importlib import reload
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

# tools is importable courtesy of conftest.py / sys.path setup
from tools.synthetic_data_generator import (
    DATA_DIR,
    _load_asn_pools,
    _load_lines,
    generate_events,
)


BUCKET = "dram-soc-honeypot-ingest"
TABLE = "dram-soc-honeypot"


@pytest.fixture(autouse=True)
def aws_creds(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("DDB_TABLE", TABLE)
    monkeypatch.setenv("RAW_TTL_DAYS", "90")
    monkeypatch.setenv("SENSOR_NAME", "honeypot")


@pytest.fixture
def synthetic_events():
    asn_pools = _load_asn_pools(DATA_DIR / "asn_pools.json")
    usernames = _load_lines(DATA_DIR / "usernames.txt")
    passwords = _load_lines(DATA_DIR / "passwords.txt")
    fixed_now = datetime(2026, 4, 27, 12, 0, tzinfo=timezone.utc)
    return list(
        generate_events(
            target_events=120,
            days=1,
            seed=2026,
            asn_pools=asn_pools,
            usernames=usernames,
            passwords=passwords,
            now=fixed_now,
        )
    )


def _put_synthetic_object(s3, key: str, events: list[dict]) -> None:
    body = "\n".join(json.dumps(e) for e in events).encode("utf-8")
    s3.put_object(
        Bucket=BUCKET,
        Key=key,
        Body=gzip.compress(body),
        ContentEncoding="gzip",
    )


def _setup(s3) -> None:
    s3.create_bucket(Bucket=BUCKET)


def _setup_ddb(ddb) -> None:
    ddb.create_table(
        TableName=TABLE,
        AttributeDefinitions=[
            {"AttributeName": "pk", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
            {"AttributeName": "gsi1pk", "AttributeType": "S"},
            {"AttributeName": "gsi1sk", "AttributeType": "S"},
            {"AttributeName": "gsi2pk", "AttributeType": "S"},
            {"AttributeName": "gsi2sk", "AttributeType": "S"},
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
        ],
    )


def _s3_event(bucket: str, key: str) -> dict:
    return {
        "Records": [
            {
                "eventVersion": "2.1",
                "eventSource": "aws:s3",
                "s3": {"bucket": {"name": bucket}, "object": {"key": key}},
            }
        ]
    }


def _import_handler():
    # Import inside the moto context so boto3 clients in module scope are
    # captured by moto's patching.
    import functions.ingest.handler as h

    return reload(h)


@mock_aws
def test_happy_path_writes_all_events(synthetic_events):
    s3 = boto3.client("s3", region_name="us-east-1")
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _setup(s3)
    _setup_ddb(ddb)

    key = "raw/2026/04/27/12/synthetic-2026-0001.json.gz"
    _put_synthetic_object(s3, key, synthetic_events)

    handler_mod = _import_handler()
    summary = handler_mod.handler(_s3_event(BUCKET, key), context=None)

    assert summary["events_validated"] == len(synthetic_events)
    assert summary["events_written"] == len(synthetic_events)
    assert summary["validation_errors"] == 0

    scan = ddb.scan(TableName=TABLE, Select="COUNT")
    assert scan["Count"] == len(synthetic_events)


@mock_aws
def test_idempotency_replay_yields_zero_net_new_items(synthetic_events):
    s3 = boto3.client("s3", region_name="us-east-1")
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _setup(s3)
    _setup_ddb(ddb)

    key = "raw/2026/04/27/12/synthetic-replay.json.gz"
    _put_synthetic_object(s3, key, synthetic_events)

    handler_mod = _import_handler()
    handler_mod.handler(_s3_event(BUCKET, key), context=None)
    first_count = ddb.scan(TableName=TABLE, Select="COUNT")["Count"]

    # Replay same object — same pk/sk derive same item; BatchWriteItem
    # PutRequest overwrites (same content), net new items = 0.
    handler_mod.handler(_s3_event(BUCKET, key), context=None)
    second_count = ddb.scan(TableName=TABLE, Select="COUNT")["Count"]

    assert first_count == second_count == len(synthetic_events)


@mock_aws
def test_malformed_lines_increment_validation_error_count(synthetic_events):
    s3 = boto3.client("s3", region_name="us-east-1")
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _setup(s3)
    _setup_ddb(ddb)

    # Mix valid events with one malformed line that should be counted but skipped.
    body_lines = [json.dumps(e) for e in synthetic_events[:50]]
    body_lines.append(json.dumps({"eventid": "cowrie.bogus.shape", "missing": "stuff"}))
    body_lines.append(json.dumps({"eventid": "cowrie.session.connect"}))  # missing required fields
    body = "\n".join(body_lines).encode("utf-8")

    key = "raw/2026/04/27/12/synthetic-with-bad.json.gz"
    s3.put_object(
        Bucket=BUCKET,
        Key=key,
        Body=gzip.compress(body),
        ContentEncoding="gzip",
    )

    handler_mod = _import_handler()
    summary = handler_mod.handler(_s3_event(BUCKET, key), context=None)

    assert summary["events_validated"] == 50
    assert summary["events_written"] == 50
    assert summary["validation_errors"] == 2


@mock_aws
def test_unrecoverable_object_failure_raises(synthetic_events):
    """A whole-object failure (e.g. S3 returns nothing) must propagate so
    Lambda's destination config can route to the DLQ. This test simulates
    a missing object key.
    """
    s3 = boto3.client("s3", region_name="us-east-1")
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _setup(s3)
    _setup_ddb(ddb)

    handler_mod = _import_handler()
    with pytest.raises(Exception):
        handler_mod.handler(
            _s3_event(BUCKET, "raw/2026/04/27/12/never-uploaded.json.gz"),
            context=None,
        )


@mock_aws
def test_synthetic_enrichment_fields_pass_through_to_stored_items():
    """Phase 7: when synthetic events carry country/asn/asn_org on the
    payload, the ingest handler pops them off before Cowrie-schema
    validation and uses them as the GeoIP enrichment for the stored item.
    Real Pi data without these fields falls back to the MaxMind layer
    (or to None when the layer isn't loaded)."""
    s3 = boto3.client("s3", region_name="us-east-1")
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _setup(s3)
    _setup_ddb(ddb)

    enriched = {
        "eventid": "cowrie.login.failed",
        "timestamp": "2026-04-29T12:00:00.000000Z",
        "src_ip": "203.0.113.7",
        "session": "synth-en-1",
        "sensor": "honeypot",
        "username": "root",
        "password": "123456",
        "message": "login attempt [root/123456] failed",
        "country": "CN",
        "asn": 4134,
        "asn_org": "Chinanet",
    }
    body = json.dumps(enriched).encode("utf-8")
    key = "raw/2026/04/29/12/synthetic-enriched.json.gz"
    s3.put_object(Bucket=BUCKET, Key=key, Body=gzip.compress(body))

    handler_mod = _import_handler()
    handler_mod.handler(_s3_event(BUCKET, key), context=None)

    items = ddb.scan(TableName=TABLE)["Items"]
    assert len(items) == 1
    item = items[0]
    assert item["country"]["S"] == "CN"
    assert int(item["asn"]["N"]) == 4134
    assert item["asn_org"]["S"] == "Chinanet"


@mock_aws
def test_password_classification_visible_in_stored_items(synthetic_events):
    s3 = boto3.client("s3", region_name="us-east-1")
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _setup(s3)
    _setup_ddb(ddb)

    # Inject one event with a password we know is in the dictionary, and one
    # we know is not.
    common_event = {
        "eventid": "cowrie.login.failed",
        "timestamp": "2026-04-27T23:30:00.000000Z",
        "src_ip": "192.0.2.99",
        "session": "dictsess0",
        "sensor": "honeypot",
        "username": "root",
        "password": "123456",  # in dictionary
        "message": "login attempt [root/123456] failed",
    }
    rare_event = {
        "eventid": "cowrie.login.failed",
        "timestamp": "2026-04-27T23:30:01.000000Z",
        "src_ip": "192.0.2.99",
        "session": "raresess0",
        "sensor": "honeypot",
        "username": "root",
        "password": "this-pw-is-not-in-our-attack-dict-72394",
        "message": "login attempt [root/...] failed",
    }
    body = "\n".join(json.dumps(e) for e in (common_event, rare_event)).encode("utf-8")
    key = "raw/2026/04/27/12/cls-test.json.gz"
    s3.put_object(Bucket=BUCKET, Key=key, Body=gzip.compress(body))

    handler_mod = _import_handler()
    handler_mod.handler(_s3_event(BUCKET, key), context=None)

    items = ddb.scan(TableName=TABLE)["Items"]
    by_session = {it["session"]["S"]: it for it in items}

    common = by_session["dictsess0"]
    rare = by_session["raresess0"]

    assert common["password"]["S"] == "123456"
    assert "password_raw" not in common  # dictionary hit → no raw stored

    rare_pw = rare["password"]["S"]
    assert rare_pw.startswith("<filtered:len=")
    assert rare["password_raw"]["S"] == "this-pw-is-not-in-our-attack-dict-72394"


# --- Phase 10: HAProxy ingest + correlation ----------------------------------


def _haproxy_record(*, time_iso: str, client_ip: str, client_port: int) -> dict:
    return {
        "time": time_iso,
        "host": "soc-honeypot-ingress",
        "process": "haproxy",
        "pid": 12345,
        "client_ip": client_ip,
        "client_port": client_port,
        "frontend_port": 22,
        "duration": 1234,
        "bytes_uploaded": 100,
        "bytes_downloaded": 200,
        "status": "cD",
        "fluent_host": "droplet",
        "fluent_source": "haproxy",
    }


def _put_ndjson_object(s3, key: str, records: list[dict]) -> None:
    body = "\n".join(json.dumps(r) for r in records).encode("utf-8")
    s3.put_object(
        Bucket=BUCKET,
        Key=key,
        Body=gzip.compress(body),
        ContentEncoding="gzip",
    )


@mock_aws
def test_haproxy_object_writes_haproxy_conn_items_under_minute_partition():
    s3 = boto3.client("s3", region_name="us-east-1")
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _setup(s3)
    _setup_ddb(ddb)

    records = [
        _haproxy_record(time_iso="2026-05-07T00:55:01.948594+00:00",
                        client_ip="104.174.33.78", client_port=8728),
        _haproxy_record(time_iso="2026-05-07T00:55:30.123456+00:00",
                        client_ip="194.59.206.2",  client_port=51000),
    ]
    key = "raw/haproxy/date=2026-05-07/host=droplet/haproxy-001.json.gz"
    _put_ndjson_object(s3, key, records)

    handler_mod = _import_handler()
    summary = handler_mod.handler(_s3_event(BUCKET, key), context=None)
    assert summary["events_validated"] == 2
    assert summary["events_written"] == 2

    items = ddb.scan(TableName=TABLE)["Items"]
    pks = {it["pk"]["S"] for it in items}
    assert pks == {"HAPROXY#2026-05-07T00:55"}
    types = {it["type"]["S"] for it in items}
    assert types == {"HAPROXY_CONN"}


def _cowrie_event(*, ts: str, session: str, eventid: str, src_ip: str = "127.0.0.1",
                  src_port: int = 50001) -> dict:
    """Minimal Cowrie session.connect-shaped event valid against the schema."""
    return {
        "eventid": eventid,
        "timestamp": ts,
        "src_ip": src_ip,
        "src_port": src_port,
        "dst_ip": "127.0.0.1",
        "dst_port": 2223,
        "session": session,
        "sensor": "honeypot",
        "protocol": "ssh",
        "uuid": "00000000-0000-1111-1111-000000000000",
    }


@mock_aws
def test_cowrie_loopback_event_correlates_to_real_haproxy_ip_when_single_match():
    s3 = boto3.client("s3", region_name="us-east-1")
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _setup(s3)
    _setup_ddb(ddb)

    # Pre-stage a HAProxy entry 50ms before Cowrie's session.connect timestamp.
    haproxy_key = "raw/haproxy/date=2026-05-07/host=droplet/haproxy-001.json.gz"
    _put_ndjson_object(
        s3, haproxy_key,
        [_haproxy_record(time_iso="2026-05-07T00:55:01.900000+00:00",
                         client_ip="203.0.113.42", client_port=44444)],
    )

    handler_mod = _import_handler()
    handler_mod.handler(_s3_event(BUCKET, haproxy_key), context=None)

    cowrie_event = _cowrie_event(
        ts="2026-05-07T00:55:01.950000Z",
        session="abc123def456",
        eventid="cowrie.session.connect",
        src_ip="127.0.0.1",
    )
    cowrie_key = "raw/cowrie/date=2026-05-07/host=pi/cowrie-001.json.gz"
    _put_ndjson_object(s3, cowrie_key, [cowrie_event])

    summary = handler_mod.handler(_s3_event(BUCKET, cowrie_key), context=None)
    assert summary["events_written"] == 1

    sess_items = ddb.query(
        TableName=TABLE,
        KeyConditionExpression="pk = :pk",
        ExpressionAttributeValues={":pk": {"S": "SESSION#abc123def456"}},
    )["Items"]
    assert len(sess_items) == 1
    item = sess_items[0]
    assert item["src_ip"]["S"] == "203.0.113.42"
    assert item["correlation_status"]["S"] == "matched"
    assert int(item["correlation_candidate_count"]["N"]) == 1
    candidate_ips = [v["S"] for v in item["correlation_candidate_ips"]["L"]]
    assert candidate_ips == ["203.0.113.42"]


@mock_aws
def test_cowrie_loopback_event_marked_missed_when_no_haproxy_in_window():
    s3 = boto3.client("s3", region_name="us-east-1")
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _setup(s3)
    _setup_ddb(ddb)

    handler_mod = _import_handler()
    cowrie_event = _cowrie_event(
        ts="2026-05-07T00:55:01.950000Z",
        session="orphan-no-haproxy",
        eventid="cowrie.session.connect",
        src_ip="127.0.0.1",
    )
    cowrie_key = "raw/cowrie/date=2026-05-07/host=pi/cowrie-only.json.gz"
    _put_ndjson_object(s3, cowrie_key, [cowrie_event])

    handler_mod.handler(_s3_event(BUCKET, cowrie_key), context=None)
    items = ddb.query(
        TableName=TABLE,
        KeyConditionExpression="pk = :pk",
        ExpressionAttributeValues={":pk": {"S": "SESSION#orphan-no-haproxy"}},
    )["Items"]
    assert len(items) == 1
    item = items[0]
    assert item["src_ip"]["S"] == "127.0.0.1"
    assert item["correlation_status"]["S"] == "missed"
    assert int(item["correlation_candidate_count"]["N"]) == 0


@mock_aws
def test_cowrie_loopback_event_marked_ambiguous_when_multiple_haproxy_in_window():
    s3 = boto3.client("s3", region_name="us-east-1")
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _setup(s3)
    _setup_ddb(ddb)

    haproxy_key = "raw/haproxy/date=2026-05-07/host=droplet/haproxy-multi.json.gz"
    _put_ndjson_object(
        s3, haproxy_key,
        [
            _haproxy_record(time_iso="2026-05-07T00:55:01.900000+00:00",
                            client_ip="203.0.113.42", client_port=44444),
            _haproxy_record(time_iso="2026-05-07T00:55:01.910000+00:00",
                            client_ip="198.51.100.1", client_port=55555),
        ],
    )

    handler_mod = _import_handler()
    handler_mod.handler(_s3_event(BUCKET, haproxy_key), context=None)

    cowrie_event = _cowrie_event(
        ts="2026-05-07T00:55:01.950000Z",
        session="ambiguous-sess",
        eventid="cowrie.session.connect",
        src_ip="127.0.0.1",
    )
    cowrie_key = "raw/cowrie/date=2026-05-07/host=pi/cowrie-amb.json.gz"
    _put_ndjson_object(s3, cowrie_key, [cowrie_event])

    handler_mod.handler(_s3_event(BUCKET, cowrie_key), context=None)
    items = ddb.query(
        TableName=TABLE,
        KeyConditionExpression="pk = :pk",
        ExpressionAttributeValues={":pk": {"S": "SESSION#ambiguous-sess"}},
    )["Items"]
    assert len(items) == 1
    item = items[0]
    # Don't pick one — keep loopback.
    assert item["src_ip"]["S"] == "127.0.0.1"
    assert item["correlation_status"]["S"] == "ambiguous"
    assert int(item["correlation_candidate_count"]["N"]) == 2
    candidate_ips = sorted(v["S"] for v in item["correlation_candidate_ips"]["L"])
    assert candidate_ips == ["198.51.100.1", "203.0.113.42"]


@mock_aws
def test_cowrie_event_with_real_src_ip_skips_correlation():
    """Phase 7 synthetic events carry their own non-loopback src_ip. They
    must NOT trigger the correlation path (which would emit a candidate
    metric and burn a DDB query).
    """
    s3 = boto3.client("s3", region_name="us-east-1")
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _setup(s3)
    _setup_ddb(ddb)

    handler_mod = _import_handler()
    cowrie_event = _cowrie_event(
        ts="2026-05-07T00:55:01.950000Z",
        session="synthetic-sess",
        eventid="cowrie.session.connect",
        src_ip="91.92.93.94",  # synthetic-shape, not loopback
    )
    cowrie_key = "raw/synthetic-2026-0001.json.gz"
    _put_ndjson_object(s3, cowrie_key, [cowrie_event])

    handler_mod.handler(_s3_event(BUCKET, cowrie_key), context=None)
    items = ddb.query(
        TableName=TABLE,
        KeyConditionExpression="pk = :pk",
        ExpressionAttributeValues={":pk": {"S": "SESSION#synthetic-sess"}},
    )["Items"]
    assert len(items) == 1
    item = items[0]
    assert item["src_ip"]["S"] == "91.92.93.94"
    # No correlation fields stored when correlation didn't run.
    assert "correlation_status" not in item


@mock_aws
def test_url_encoded_key_in_s3_event_is_decoded_before_get_object():
    """S3 event notifications URL-encode object keys. fluent-bit writes
    literal `=` in `date=YYYY-MM-DD/host=pi/`, which the event delivers
    as `%3D`. The Lambda must unquote the key before calling get_object,
    or every real-traffic invocation fails AccessDenied (an S3 misnomer
    for "object doesn't exist + ListBucket not granted").
    """
    s3 = boto3.client("s3", region_name="us-east-1")
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _setup(s3)
    _setup_ddb(ddb)

    real_key = "raw/cowrie/date=2026-05-07/host=pi/cowrie-001.json.gz"
    cowrie_event = _cowrie_event(
        ts="2026-05-07T00:55:01.950000Z",
        session="urlenc-test",
        eventid="cowrie.session.connect",
        src_ip="91.92.93.94",
    )
    _put_ndjson_object(s3, real_key, [cowrie_event])

    # S3 event notification URL-encodes `=` to `%3D`.
    encoded_key = real_key.replace("=", "%3D")
    handler_mod = _import_handler()
    summary = handler_mod.handler(_s3_event(BUCKET, encoded_key), context=None)
    assert summary["events_written"] == 1


# --- Backward correlation (HAProxy lands AFTER Cowrie) -----------------------


@mock_aws
def test_haproxy_backward_correlation_matches_pending_session():
    """When a Cowrie batch lands first (correlation_status=missed) and a
    HAProxy batch with a matching timestamp lands later, the HAProxy
    ingest path must update the pre-existing SESSION events."""
    s3 = boto3.client("s3", region_name="us-east-1")
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _setup(s3)
    _setup_ddb(ddb)

    # Stage 1: Cowrie session arrives first; correlation misses.
    cowrie_event = _cowrie_event(
        ts="2026-05-07T05:13:53.241412Z",
        session="back-corr-pending",
        eventid="cowrie.session.connect",
        src_ip="127.0.0.1",
    )
    # cowrie.session.params has no extra-required fields under check_fields,
    # so it stays valid without us inventing username/password — keeps the
    # test focused on the backward-correlation path.
    cowrie_login = _cowrie_event(
        ts="2026-05-07T05:13:54.500000Z",  # second event in same session
        session="back-corr-pending",
        eventid="cowrie.session.params",
        src_ip="127.0.0.1",
    )
    cowrie_key = "raw/cowrie/date=2026-05-07/host=pi/cowrie-back-corr.json.gz"
    _put_ndjson_object(s3, cowrie_key, [cowrie_event, cowrie_login])

    handler_mod = _import_handler()
    handler_mod.handler(_s3_event(BUCKET, cowrie_key), context=None)

    # Confirm the precondition: events stored as missed.
    pre = ddb.query(
        TableName=TABLE,
        KeyConditionExpression="pk = :pk",
        ExpressionAttributeValues={":pk": {"S": "SESSION#back-corr-pending"}},
    )["Items"]
    assert len(pre) == 2
    assert all(it["correlation_status"]["S"] == "missed" for it in pre)
    assert all(it["src_ip"]["S"] == "127.0.0.1" for it in pre)

    # Stage 2: HAProxy batch with a matching timestamp arrives.
    # 92ms before the Cowrie session.connect — same as the live test delta.
    haproxy_key = "raw/haproxy/date=2026-05-07/host=droplet/haproxy-back-corr.json.gz"
    _put_ndjson_object(
        s3, haproxy_key,
        [_haproxy_record(time_iso="2026-05-07T05:13:53.149191+00:00",
                         client_ip="203.0.113.42", client_port=44444)],
    )
    handler_mod.handler(_s3_event(BUCKET, haproxy_key), context=None)

    post = ddb.query(
        TableName=TABLE,
        KeyConditionExpression="pk = :pk",
        ExpressionAttributeValues={":pk": {"S": "SESSION#back-corr-pending"}},
    )["Items"]
    assert len(post) == 2
    for item in post:
        assert item["src_ip"]["S"] == "203.0.113.42"
        assert item["correlation_status"]["S"] == "matched"
        assert int(item["correlation_candidate_count"]["N"]) == 1
        assert item["gsi1pk"]["S"] == "IP#203.0.113.42"
        candidate_ips = [v["S"] for v in item["correlation_candidate_ips"]["L"]]
        assert candidate_ips == ["203.0.113.42"]


@mock_aws
def test_haproxy_backward_correlation_skips_already_matched():
    """When forward correlation has already marked a session matched (with
    one IP), a later HAProxy entry that would also be in the window must
    NOT overwrite the prior IP. The conditional update prevents the
    `last writer wins` footgun."""
    s3 = boto3.client("s3", region_name="us-east-1")
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _setup(s3)
    _setup_ddb(ddb)

    # First HAProxy → first Cowrie: forward correlation succeeds.
    haproxy_key1 = "raw/haproxy/date=2026-05-07/host=droplet/h1.json.gz"
    _put_ndjson_object(
        s3, haproxy_key1,
        [_haproxy_record(time_iso="2026-05-07T05:13:53.100000+00:00",
                         client_ip="198.51.100.1", client_port=11111)],
    )
    cowrie_key = "raw/cowrie/date=2026-05-07/host=pi/c1.json.gz"
    _put_ndjson_object(
        s3, cowrie_key,
        [_cowrie_event(ts="2026-05-07T05:13:53.200000Z",
                       session="already-matched", eventid="cowrie.session.connect",
                       src_ip="127.0.0.1")],
    )

    handler_mod = _import_handler()
    handler_mod.handler(_s3_event(BUCKET, haproxy_key1), context=None)
    handler_mod.handler(_s3_event(BUCKET, cowrie_key), context=None)

    # Sanity: forward correlation should have set src_ip to 198.51.100.1.
    pre = ddb.query(
        TableName=TABLE,
        KeyConditionExpression="pk = :pk",
        ExpressionAttributeValues={":pk": {"S": "SESSION#already-matched"}},
    )["Items"]
    assert len(pre) == 1
    assert pre[0]["src_ip"]["S"] == "198.51.100.1"
    assert pre[0]["correlation_status"]["S"] == "matched"

    # Now a competing HAProxy entry arrives in the same window with a
    # DIFFERENT IP. Backward correlation must NOT overwrite the existing
    # matched event (the conditional update fails with
    # ConditionalCheckFailedException, which we catch and log).
    haproxy_key2 = "raw/haproxy/date=2026-05-07/host=droplet/h2.json.gz"
    _put_ndjson_object(
        s3, haproxy_key2,
        [_haproxy_record(time_iso="2026-05-07T05:13:53.110000+00:00",
                         client_ip="192.0.2.99", client_port=22222)],
    )
    handler_mod.handler(_s3_event(BUCKET, haproxy_key2), context=None)

    post = ddb.query(
        TableName=TABLE,
        KeyConditionExpression="pk = :pk",
        ExpressionAttributeValues={":pk": {"S": "SESSION#already-matched"}},
    )["Items"]
    # IP must remain the original (198.51.100.1), NOT the new one (192.0.2.99).
    assert post[0]["src_ip"]["S"] == "198.51.100.1"
    assert post[0]["correlation_status"]["S"] == "matched"


@mock_aws
def test_haproxy_backward_correlation_no_candidates_no_ops():
    """When a HAProxy batch lands with no Cowrie sessions in the window,
    backward correlation issues zero UpdateItem calls (no-op)."""
    s3 = boto3.client("s3", region_name="us-east-1")
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _setup(s3)
    _setup_ddb(ddb)

    handler_mod = _import_handler()
    haproxy_key = "raw/haproxy/date=2026-05-07/host=droplet/empty-window.json.gz"
    _put_ndjson_object(
        s3, haproxy_key,
        [_haproxy_record(time_iso="2026-05-07T05:13:53.000000+00:00",
                         client_ip="203.0.113.99", client_port=33333)],
    )
    summary = handler_mod.handler(_s3_event(BUCKET, haproxy_key), context=None)
    assert summary["events_written"] == 1

    # Only the HAPROXY_CONN item exists; no SESSION events anywhere.
    scan = ddb.scan(TableName=TABLE)["Items"]
    types = {it.get("type", {}).get("S") for it in scan}
    assert types == {"HAPROXY_CONN"}


def test_unit_cowrie_src_port_is_not_haproxy_client_port():
    """Defensive unit doc-test: Cowrie's `src_port` is the Pi-side
    ephemeral port the kernel assigns when autossh forwards the bytes to
    Cowrie's listener. HAProxy's `client_port` is the attacker's source
    port. They have no relation. ADR-010 captures why this is true; this
    test pins a regression so future code that tries to "join on src_port"
    is forced to read ADR-010 first.
    """
    haproxy = _haproxy_record(
        time_iso="2026-05-07T00:55:01.900000+00:00",
        client_ip="203.0.113.42",
        client_port=44444,  # attacker-side source port — what HAProxy logs
    )
    cowrie = _cowrie_event(
        ts="2026-05-07T00:55:01.950000Z",
        session="x",
        eventid="cowrie.session.connect",
        src_ip="127.0.0.1",
        src_port=50001,  # Pi-side ephemeral — what Cowrie logs
    )
    assert haproxy["client_port"] != cowrie["src_port"]
