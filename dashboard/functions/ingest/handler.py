from __future__ import annotations

import gzip
import hashlib
import io
import json
import logging
import os
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

import boto3
from botocore.exceptions import ClientError
from pydantic import ValidationError

from functions.shared.cowrie_schema import CowrieEvent
from functions.shared.event_dto import StoredEvent
from functions.shared.geoip import GeoIPEnricher, GeoIPLookup
from functions.shared.password_classifier import (
    classify_password,
    load_dictionary,
)

logger = logging.getLogger("dram-soc.ingest")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))


def _log(event: str, /, **kwargs: Any) -> None:
    """Structured JSON log line. Never include raw payloads or secrets."""
    logger.info(json.dumps({"event": event, **kwargs}))


# --- Cold-start singletons ----------------------------------------------------

TABLE_NAME = os.environ.get("DDB_TABLE", "dram-soc-honeypot")
RAW_TTL_DAYS = int(os.environ.get("RAW_TTL_DAYS", "90"))
SENSOR_NAME = os.environ.get("SENSOR_NAME", "honeypot")

_S3 = boto3.client("s3")
_DDB = boto3.client("dynamodb")
_DICTIONARY = load_dictionary()


def _get_enricher() -> GeoIPEnricher | None:
    """Lazy-build the enricher; returns None if the layer isn't present
    (lets unit tests run without the .mmdb files in CI).
    """
    try:
        return GeoIPEnricher.from_layer()
    except Exception as exc:  # noqa: BLE001
        _log("geoip_layer_unavailable", error=type(exc).__name__)
        return None


_ENRICHER = _get_enricher()

# --- Helpers ------------------------------------------------------------------


def _ingest_id(event: dict[str, Any]) -> str:
    return hashlib.sha1(
        f"{event['session']}|{event['timestamp']}|{event['eventid']}".encode("utf-8")
    ).hexdigest()


def _ttl_for(event_ts: str) -> int:
    base = datetime.fromisoformat(event_ts.replace("Z", "+00:00"))
    return int((base + timedelta(days=RAW_TTL_DAYS)).timestamp())


def _build_stored_event(
    raw: dict[str, Any],
    *,
    enrichment: GeoIPLookup,
) -> StoredEvent:
    public_pw, raw_pw = classify_password(raw.get("password"), _DICTIONARY)
    ts = raw["timestamp"]
    session = raw["session"]
    eventid = raw["eventid"]
    src_ip = raw["src_ip"]

    return StoredEvent(
        pk=f"SESSION#{session}",
        sk=f"{ts}#{eventid}",
        gsi1pk=f"IP#{src_ip}",
        gsi1sk=ts,
        gsi2pk=f"DAY#{ts[:10]}",
        gsi2sk=f"{ts}#SESSION#{session}",
        eventid=eventid,
        session=session,
        src_ip=src_ip,
        sensor=raw.get("sensor", SENSOR_NAME),
        ts=ts,
        ingest_id=f"sha1:{_ingest_id(raw)}",
        ttl=_ttl_for(ts),
        src_port=raw.get("src_port"),
        dst_ip=raw.get("dst_ip"),
        dst_port=raw.get("dst_port"),
        protocol=raw.get("protocol"),
        sensor_uuid=raw.get("uuid"),
        message=raw.get("message"),
        username=raw.get("username"),
        password=public_pw,
        password_raw=raw_pw,
        version=raw.get("version"),
        hassh=raw.get("hassh"),
        input=raw.get("input"),
        url=raw.get("url"),
        outfile=raw.get("outfile"),
        shasum=raw.get("shasum"),
        duration=raw.get("duration"),
        country=enrichment.country,
        asn=enrichment.asn,
        asn_org=enrichment.asn_org,
    )


def _to_ddb_attr(value: Any) -> dict[str, Any]:
    """Convert a Python value to a DynamoDB low-level attribute value."""
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
    if isinstance(value, list):
        return {"L": [_to_ddb_attr(v) for v in value]}
    if isinstance(value, dict):
        return {"M": {k: _to_ddb_attr(v) for k, v in value.items()}}
    raise TypeError(f"Unsupported DDB attribute type: {type(value)!r}")


def _stored_event_to_item(stored: StoredEvent) -> dict[str, Any]:
    payload = stored.model_dump(exclude_none=True)
    return {k: _to_ddb_attr(v) for k, v in payload.items()}


def _chunked(items: list[dict[str, Any]], size: int) -> Iterable[list[dict[str, Any]]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _batch_write_with_retries(items: list[dict[str, Any]]) -> int:
    """Write items in chunks of 25, retrying UnprocessedItems with backoff.

    Returns the number of successfully persisted items. Raises the underlying
    ClientError if a non-retryable error escapes the retry loop.

    Idempotency: BatchWriteItem itself is idempotent for identical PutItem
    payloads with the same keys (re-writes the same item). Combined with the
    deterministic ingest_id, replaying the same S3 object yields identical
    items and zero net change in DDB content. Per-key conditional writes
    aren't used here (BatchWriteItem doesn't support them); duplicate
    detection is downstream/eventual: the aggregator dedupes by ingest_id.
    """
    written = 0
    for chunk in _chunked(items, 25):
        request_items = {TABLE_NAME: [{"PutRequest": {"Item": it}} for it in chunk]}
        attempts = 0
        backoff = 0.1
        while request_items:
            attempts += 1
            try:
                resp = _DDB.batch_write_item(RequestItems=request_items)
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code", "")
                if code in {"ProvisionedThroughputExceededException",
                            "RequestLimitExceeded",
                            "ThrottlingException"}:
                    if attempts > 10:
                        raise
                    time.sleep(min(backoff, 30.0))
                    backoff *= 2
                    continue
                raise
            unprocessed = resp.get("UnprocessedItems", {}).get(TABLE_NAME, [])
            written += len(chunk) - len(unprocessed)
            chunk = [it["PutRequest"]["Item"] for it in unprocessed]
            if not unprocessed:
                request_items = {}
                break
            if attempts > 10:
                _log("batch_write_unprocessed_giveup", remaining=len(unprocessed))
                raise RuntimeError(
                    f"giving up with {len(unprocessed)} unprocessed items"
                )
            request_items = {TABLE_NAME: unprocessed}
            time.sleep(min(backoff, 30.0))
            backoff *= 2
    return written


def _read_object_lines(bucket: str, key: str) -> list[dict[str, Any]]:
    body = _S3.get_object(Bucket=bucket, Key=key)["Body"].read()
    if key.endswith(".gz"):
        body = gzip.decompress(body)
    out: list[dict[str, Any]] = []
    for line in io.BytesIO(body).read().splitlines():
        if not line.strip():
            continue
        out.append(json.loads(line))
    return out


def _process_object(bucket: str, key: str) -> dict[str, int]:
    raw_events = _read_object_lines(bucket, key)
    stored: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for raw in raw_events:
        # Synthetic events ship country/asn/asn_org pre-baked. Strip those
        # before Cowrie-schema validation (the schema is extra="forbid"; the
        # Cowrie shape is canonical, the enrichment is ours). When present,
        # they take precedence over GeoIP lookup; absent, fall back to the
        # MaxMind layer.
        src_country = raw.pop("country", None)
        src_asn = raw.pop("asn", None)
        src_asn_org = raw.pop("asn_org", None)

        try:
            CowrieEvent.model_validate(raw).check_fields()
        except (ValidationError, ValueError) as exc:
            counts["validation_error"] += 1
            _log(
                "event_invalid",
                eventid=raw.get("eventid"),
                error=type(exc).__name__,
            )
            continue

        if src_country is not None:
            enrichment = GeoIPLookup(
                country=src_country,
                asn=int(src_asn) if src_asn is not None else None,
                asn_org=src_asn_org,
            )
        elif _ENRICHER is not None:
            enrichment = _ENRICHER.enrich(raw["src_ip"])
        else:
            enrichment = GeoIPLookup(country=None, asn=None, asn_org=None)
        stored_evt = _build_stored_event(raw, enrichment=enrichment)
        stored.append(_stored_event_to_item(stored_evt))
        counts["validated"] += 1

    if not stored:
        return {"objects_read": 1, "events_validated": 0, "events_written": 0,
                "validation_errors": counts.get("validation_error", 0)}

    written = _batch_write_with_retries(stored)
    return {
        "objects_read": 1,
        "events_validated": counts["validated"],
        "events_written": written,
        "validation_errors": counts.get("validation_error", 0),
    }


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entrypoint."""
    totals = Counter({"objects_read": 0, "events_validated": 0,
                      "events_written": 0, "validation_errors": 0})
    for record in event.get("Records", []):
        s3_record = record.get("s3", {})
        bucket = s3_record.get("bucket", {}).get("name")
        key = s3_record.get("object", {}).get("key")
        if not bucket or not key:
            _log("malformed_event_record", record_keys=list(record.keys()))
            continue
        result = _process_object(bucket, key)
        for k, v in result.items():
            totals[k] += v
        _log("object_processed", bucket=bucket, key=key, **result)

    _log("invocation_summary", **dict(totals))
    return dict(totals)
