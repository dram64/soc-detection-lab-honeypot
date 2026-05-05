"""moto-backed tests for the generator's S3 and DynamoDB injection paths.

These exercise the boto3-using helpers (upload_to_s3, inject_to_dynamodb, and
the corresponding --upload-s3 / --inject-ddb branches of main()) without
hitting any real AWS endpoint.
"""

from __future__ import annotations

import gzip
import json

import boto3
import pytest
from moto import mock_aws

from tools.synthetic_data_generator import (
    generate_events,
    inject_to_dynamodb,
    main,
    upload_to_s3,
    _load_asn_pools,
    _load_lines,
    DATA_DIR,
)
from datetime import datetime, timezone


@pytest.fixture(autouse=True)
def aws_creds(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


@pytest.fixture
def small_events():
    asn_pools = _load_asn_pools(DATA_DIR / "asn_pools.json")
    usernames = _load_lines(DATA_DIR / "usernames.txt")
    passwords = _load_lines(DATA_DIR / "passwords.txt")
    fixed_now = datetime(2026, 4, 27, 12, 0, tzinfo=timezone.utc)
    return list(
        generate_events(
            target_events=120,
            days=1,
            seed=99,
            asn_pools=asn_pools,
            usernames=usernames,
            passwords=passwords,
            now=fixed_now,
        )
    )


@mock_aws
def test_upload_to_s3_writes_gzipped_objects(small_events):
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="dram-soc-honeypot-ingest")

    upload_to_s3(small_events, "dram-soc-honeypot-ingest", seed=99, profile=None)

    listing = s3.list_objects_v2(Bucket="dram-soc-honeypot-ingest", Prefix="raw/")
    assert listing["KeyCount"] >= 1

    # Round-trip a single object: every line must be valid Cowrie JSON.
    one = listing["Contents"][0]
    body = s3.get_object(Bucket="dram-soc-honeypot-ingest", Key=one["Key"])["Body"].read()
    decoded = gzip.decompress(body).decode("utf-8")
    for line in decoded.splitlines():
        parsed = json.loads(line)
        assert "eventid" in parsed and "session" in parsed


@mock_aws
def test_inject_to_dynamodb_writes_items(small_events):
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    ddb.create_table(
        TableName="dram-soc-honeypot",
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

    inject_to_dynamodb(small_events, "dram-soc-honeypot", profile=None)

    # Spot-check: at least one item with pk SESSION#... exists.
    scan = ddb.scan(TableName="dram-soc-honeypot", Limit=5)
    assert scan["Count"] >= 1
    sample_pk = scan["Items"][0]["pk"]["S"]
    assert sample_pk.startswith("SESSION#")


@mock_aws
def test_main_upload_s3(monkeypatch):
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="dram-soc-honeypot-ingest")

    rc = main(
        [
            "--events", "60",
            "--days", "1",
            "--seed", "5",
            "--upload-s3", "dram-soc-honeypot-ingest",
        ]
    )
    assert rc == 0
    assert s3.list_objects_v2(Bucket="dram-soc-honeypot-ingest", Prefix="raw/")["KeyCount"] >= 1


@mock_aws
def test_main_inject_ddb():
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    ddb.create_table(
        TableName="dram-soc-honeypot",
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

    rc = main(
        [
            "--events", "60",
            "--days", "1",
            "--seed", "5",
            "--inject-ddb",
            "--table", "dram-soc-honeypot",
        ]
    )
    assert rc == 0
    assert ddb.scan(TableName="dram-soc-honeypot", Limit=1)["Count"] >= 1
