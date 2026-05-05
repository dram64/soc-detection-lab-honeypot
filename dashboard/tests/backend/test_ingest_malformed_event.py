"""Test that a malformed S3 event (missing bucket/key) is logged and skipped
rather than crashing the whole invocation.
"""

from __future__ import annotations

from importlib import reload

import boto3
import pytest
from moto import mock_aws


@pytest.fixture(autouse=True)
def aws_creds(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("DDB_TABLE", "dram-soc-honeypot")


@mock_aws
def test_malformed_s3_record_skipped():
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

    import functions.ingest.handler as h

    h = reload(h)
    # Event with no s3 block at all — should not crash.
    summary = h.handler({"Records": [{"eventSource": "aws:something-else"}]}, context=None)
    assert summary["objects_read"] == 0
    assert summary["events_validated"] == 0
