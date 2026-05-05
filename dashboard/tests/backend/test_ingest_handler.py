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
        ],
        KeySchema=[
            {"AttributeName": "pk", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
        BillingMode="PAY_PER_REQUEST",
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
