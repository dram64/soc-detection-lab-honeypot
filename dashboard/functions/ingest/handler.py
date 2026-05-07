from __future__ import annotations

import gzip
import hashlib
import io
import json
import logging
import os
import time
import urllib.parse
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

import boto3
from botocore.exceptions import ClientError
from pydantic import ValidationError

from functions.shared.cowrie_schema import CowrieEvent
from functions.shared.event_dto import StoredEvent
from functions.shared.geoip import GeoIPEnricher, GeoIPLookup
from functions.shared.haproxy_parser import (
    HAProxyRecord,
    buckets_for_window,
    cowrie_ts_to_us,
)
from functions.shared.haproxy_parser import (
    parse_record as parse_haproxy_record,
)
from functions.shared.haproxy_parser import (
    to_ddb_item as haproxy_to_ddb_item,
)
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
# Correlation window in microseconds. Initial Phase 10 hypothesis was
# 200ms (ADR-010 §Decision); empirical observation of real bot-scanner
# traffic from RO/RU showed handshake-completion latency clustering at
# 234–275ms, missing the 200ms window for ~100% of recent sessions.
# Widened to 500ms based on production data (ADR-010 §Empirical
# window-tuning). BackwardCorrelationOutcomes{result=ambiguous} is
# the metric to watch — sustained >5% rate would indicate the window
# is now too wide and concurrent-arrival cross-attribution is risky.
CORRELATION_WINDOW_US = int(os.environ.get("CORRELATION_WINDOW_US", "500000"))
# Lower bound of the window: HAProxy logs the connection acceptance, then
# the bytes traverse the SSH tunnel before Cowrie's session.connect fires.
# A 1ms floor avoids matching same-microsecond entries that are almost
# certainly not the same connection.
CORRELATION_MIN_DELTA_US = int(os.environ.get("CORRELATION_MIN_DELTA_US", "1000"))

_S3 = boto3.client("s3")
_DDB = boto3.client("dynamodb")
_DICTIONARY = load_dictionary()


def _get_enricher() -> GeoIPEnricher | None:
    try:
        return GeoIPEnricher.from_layer()
    except Exception as exc:
        _log("geoip_layer_unavailable", error=type(exc).__name__)
        return None


_ENRICHER = _get_enricher()

# --- Helpers ------------------------------------------------------------------


def _ingest_id(event: dict[str, Any]) -> str:
    return hashlib.sha1(
        f"{event['session']}|{event['timestamp']}|{event['eventid']}".encode()
    ).hexdigest()


def _ttl_for(event_ts: str) -> int:
    base = datetime.fromisoformat(event_ts.replace("Z", "+00:00"))
    return int((base + timedelta(days=RAW_TTL_DAYS)).timestamp())


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


def _haproxy_item_to_attrs(item: dict[str, Any]) -> dict[str, Any]:
    """Convert a haproxy_parser.to_ddb_item dict to DDB attribute form."""
    return {k: _to_ddb_attr(v) for k, v in item.items() if v is not None}


def _emit_metric(name: str, value: float, *, dimensions: dict[str, str] | None = None,
                 unit: str = "Count") -> None:
    """Emit a CloudWatch custom metric via Embedded Metric Format.

    Cheaper than PutMetricData (no API call); CloudWatch parses the EMF
    JSON from the log line. ADR-010 names CorrelationCandidateCount as a
    measurement primitive informing whether Phase 10.5 is justified.
    """
    dims = dimensions or {}
    record: dict[str, Any] = {
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [{
                "Namespace": "DramSoc/Edge",
                "Dimensions": [list(dims.keys())] if dims else [[]],
                "Metrics": [{"Name": name, "Unit": unit}],
            }],
        },
        name: value,
    }
    record.update(dims)
    logger.info(json.dumps(record))


# --- Correlation --------------------------------------------------------------


def _query_haproxy_window(cowrie_ts_us: int) -> list[HAProxyRecord]:
    """Return all HAProxy records whose ts_us falls in
        [cowrie_ts_us - CORRELATION_WINDOW_US,
         cowrie_ts_us - CORRELATION_MIN_DELTA_US]
    """
    lo_us = cowrie_ts_us - CORRELATION_WINDOW_US
    hi_us = cowrie_ts_us - CORRELATION_MIN_DELTA_US
    if hi_us <= lo_us:
        return []

    candidates: list[HAProxyRecord] = []
    for bucket in buckets_for_window(cowrie_ts_us, window_us=CORRELATION_WINDOW_US):
        last_evaluated: dict[str, Any] | None = None
        while True:
            kwargs: dict[str, Any] = {
                "TableName": TABLE_NAME,
                "KeyConditionExpression": "pk = :pk",
                "ExpressionAttributeValues": {":pk": {"S": f"HAPROXY#{bucket}"}},
            }
            if last_evaluated is not None:
                kwargs["ExclusiveStartKey"] = last_evaluated
            resp = _DDB.query(**kwargs)
            for item in resp.get("Items", []):
                ts_us = int(item.get("ts_us", {}).get("N", "0"))
                if lo_us <= ts_us <= hi_us:
                    candidates.append(HAProxyRecord(
                        ts=item["ts"]["S"],
                        ts_us=ts_us,
                        client_ip=item["client_ip"]["S"],
                        client_port=int(item["client_port"]["N"]),
                        frontend_port=int(item.get("frontend_port", {}).get("N", "0")),
                        duration=int(item.get("duration", {}).get("N", "0")),
                        bytes_uploaded=int(item.get("bytes_uploaded", {}).get("N", "0")),
                        bytes_downloaded=int(item.get("bytes_downloaded", {}).get("N", "0")),
                        status=item.get("status", {}).get("S", ""),
                    ))
            last_evaluated = resp.get("LastEvaluatedKey")
            if not last_evaluated:
                break
    return candidates


def _correlate(cowrie_ts: str) -> tuple[str, list[HAProxyRecord]]:
    """Return (status, candidates) where status is one of
    {"matched", "missed", "ambiguous"}.
    """
    cowrie_us = cowrie_ts_to_us(cowrie_ts)
    candidates = _query_haproxy_window(cowrie_us)

    _emit_metric("CorrelationCandidateCount", float(len(candidates)),
                 dimensions={"Source": "cowrie"})

    if len(candidates) == 0:
        return "missed", []
    if len(candidates) == 1:
        return "matched", candidates
    return "ambiguous", candidates


def _build_stored_event(
    raw: dict[str, Any],
    *,
    enrichment: GeoIPLookup,
    src_ip: str,
    correlation_status: str | None,
    correlation_candidate_count: int | None,
    correlation_candidate_ips: list[str] | None,
) -> StoredEvent:
    public_pw, raw_pw = classify_password(raw.get("password"), _DICTIONARY)
    ts = raw["timestamp"]
    session = raw["session"]
    eventid = raw["eventid"]

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
        correlation_status=correlation_status,
        correlation_candidate_count=correlation_candidate_count,
        correlation_candidate_ips=correlation_candidate_ips,
    )


# --- DDB writers --------------------------------------------------------------


def _chunked(items: list[dict[str, Any]], size: int) -> Iterable[list[dict[str, Any]]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _batch_write_with_retries(items: list[dict[str, Any]]) -> int:
    """Write items in chunks of 25, retrying UnprocessedItems with backoff."""
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


# --- Object readers + per-source processors -----------------------------------


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


def _backward_correlate(rec: HAProxyRecord) -> None:
    """When a new HAProxy record lands, look BACK for SESSION events that
    already arrived (correlation_status=missed/ambiguous) within the
    response window and update them with the real client IP.

    Pairs with the forward pass in `_process_cowrie_object`. Each side
    handles the case where the OTHER source's batch landed first in S3.
    Order of arrival is non-deterministic at fluent-bit's 60s flush
    cadence, so both passes are required for correlation to actually
    work in production. ADR-010 §Decision describes the primitive;
    this is the bidirectional implementation.

    Update is conditional: only events whose `correlation_status` is
    currently `missed`, `ambiguous`, or absent are touched. Events that
    forward correlation has already marked `matched` are NOT overwritten,
    even if this HAProxy record would have been a different (or "better")
    candidate. The skip is logged + counted so we can observe race rates.
    """
    haproxy_dt = datetime.fromtimestamp(rec.ts_us / 1_000_000, tz=UTC)
    lo_dt = haproxy_dt + timedelta(microseconds=CORRELATION_MIN_DELTA_US)
    hi_dt = haproxy_dt + timedelta(microseconds=CORRELATION_WINDOW_US)

    def _fmt_cowrie_ts(dt: datetime) -> str:
        # Cowrie writes ts as `YYYY-MM-DDTHH:MM:SS.uuuuuuZ` — match it
        # for lexicographic comparison against gsi2sk values.
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond:06d}Z"

    lo_ts = _fmt_cowrie_ts(lo_dt)
    # `~` (ASCII 126) sorts higher than alphanumerics + `#`, bracketing the
    # gsi2sk shape `<ts>#SESSION#<id>` so BETWEEN includes events at the
    # exact upper-bound timestamp regardless of session id suffix.
    hi_ts_inclusive = f"{_fmt_cowrie_ts(hi_dt)}~"

    # Window may straddle midnight UTC if HAProxy lands within the window
    # of a date boundary. Build both DAY partitions when that's true.
    days = sorted({lo_dt.strftime("%Y-%m-%d"), hi_dt.strftime("%Y-%m-%d")})

    candidate_items: list[dict[str, Any]] = []
    for day in days:
        last_evaluated: dict[str, Any] | None = None
        while True:
            kwargs: dict[str, Any] = {
                "TableName": TABLE_NAME,
                "IndexName": "gsi2",
                "KeyConditionExpression": "gsi2pk = :pk AND gsi2sk BETWEEN :lo AND :hi",
                "ExpressionAttributeValues": {
                    ":pk": {"S": f"DAY#{day}"},
                    ":lo": {"S": lo_ts},
                    ":hi": {"S": hi_ts_inclusive},
                },
            }
            if last_evaluated is not None:
                kwargs["ExclusiveStartKey"] = last_evaluated
            resp = _DDB.query(**kwargs)
            candidate_items.extend(resp.get("Items", []))
            last_evaluated = resp.get("LastEvaluatedKey")
            if not last_evaluated:
                break

    # Restrict to loopback-IP events — those are the correlation candidates.
    loopback_items = [
        it for it in candidate_items
        if it.get("src_ip", {}).get("S") == "127.0.0.1"
    ]
    sessions_in_window = {
        it["session"]["S"] for it in loopback_items if "session" in it
    }

    if not sessions_in_window:
        _emit_metric("BackwardCorrelationOutcomes", 1.0,
                     dimensions={"result": "no_candidates"})
        return

    if len(sessions_in_window) > 1:
        _emit_metric("BackwardCorrelationOutcomes", 1.0,
                     dimensions={"result": "ambiguous"})
        return

    target_session = next(iter(sessions_in_window))
    real_ip = rec.client_ip

    # Pull all events of the matched session, then conditional-update each.
    sess_resp = _DDB.query(
        TableName=TABLE_NAME,
        KeyConditionExpression="pk = :pk",
        ExpressionAttributeValues={":pk": {"S": f"SESSION#{target_session}"}},
    )

    # Run GeoIP on the now-known real IP — events that arrived first would
    # have had the enricher run against 127.0.0.1 (returning None for all
    # fields), so backward correlation must overwrite the geo enrichment
    # too or the dashboard's GeoMap stays empty for any session that hit
    # the backward path.
    geo_set_parts: list[str] = []
    geo_values: dict[str, dict[str, Any]] = {}
    if _ENRICHER is not None:
        enrich = _ENRICHER.enrich(real_ip)
        if enrich.country is not None:
            geo_set_parts.append("country = :country")
            geo_values[":country"] = {"S": enrich.country}
        if enrich.asn is not None:
            geo_set_parts.append("asn = :asn")
            geo_values[":asn"] = {"N": str(enrich.asn)}
        if enrich.asn_org is not None:
            geo_set_parts.append("asn_org = :asn_org")
            geo_values[":asn_org"] = {"S": enrich.asn_org}

    base_set_parts = [
        "src_ip = :ip",
        "gsi1pk = :gsi1pk",
        "correlation_status = :status",
        "correlation_candidate_count = :count",
        "correlation_candidate_ips = :ips",
    ]
    update_expression = "SET " + ", ".join(base_set_parts + geo_set_parts)

    updated = 0
    skipped_already_matched = 0
    for item in sess_resp.get("Items", []):
        if item.get("type", {}).get("S") != "EVENT":
            continue
        sk = item["sk"]["S"]
        try:
            _DDB.update_item(
                TableName=TABLE_NAME,
                Key={"pk": {"S": f"SESSION#{target_session}"}, "sk": {"S": sk}},
                UpdateExpression=update_expression,
                ConditionExpression=(
                    "attribute_not_exists(correlation_status) "
                    "OR correlation_status IN (:missed, :ambiguous)"
                ),
                ExpressionAttributeValues={
                    ":ip": {"S": real_ip},
                    ":gsi1pk": {"S": f"IP#{real_ip}"},
                    ":status": {"S": "matched"},
                    ":count": {"N": "1"},
                    ":ips": {"L": [{"S": real_ip}]},
                    ":missed": {"S": "missed"},
                    ":ambiguous": {"S": "ambiguous"},
                    **geo_values,
                },
            )
            updated += 1
        except _DDB.exceptions.ConditionalCheckFailedException:
            skipped_already_matched += 1
            _log("backward_correlation_skipped_already_matched",
                 session=target_session, sk=sk)

    if updated > 0:
        _emit_metric("BackwardCorrelationOutcomes", 1.0,
                     dimensions={"result": "matched_new"})
    elif skipped_already_matched > 0:
        _emit_metric("BackwardCorrelationOutcomes", 1.0,
                     dimensions={"result": "matched_skipped_already_matched"})


def _process_haproxy_object(bucket: str, key: str) -> dict[str, int]:
    raw_records = _read_object_lines(bucket, key)
    items: list[dict[str, Any]] = []
    parsed_records: list[HAProxyRecord] = []
    counts: Counter[str] = Counter()
    for raw in raw_records:
        rec = parse_haproxy_record(raw)
        if rec is None:
            counts["parse_error"] += 1
            continue
        items.append(_haproxy_item_to_attrs(haproxy_to_ddb_item(rec, ttl_days=RAW_TTL_DAYS)))
        parsed_records.append(rec)
        counts["parsed"] += 1

    if not items:
        return {"objects_read": 1, "events_validated": 0, "events_written": 0,
                "validation_errors": counts.get("parse_error", 0)}

    written = _batch_write_with_retries(items)

    # Backward correlation pass — for each just-written HAProxy record,
    # find SESSION events that arrived first (and so missed forward
    # correlation) and update them. Bidirectional design per ADR-010.
    for rec in parsed_records:
        _backward_correlate(rec)

    return {
        "objects_read": 1,
        "events_validated": counts["parsed"],
        "events_written": written,
        "validation_errors": counts.get("parse_error", 0),
    }


def _lookup_session_prior_match(session_id: str) -> str | None:
    """Return the real client IP from any prior matched/matched_inherited
    event of the same session, or None if no prior match exists.

    This is the "forward inheritance" lookup that handles the case where
    a session's events are split across Cowrie batches: the connect event
    landed in batch A and was correlated; later events arrive in batch B
    whose timestamps fall outside the 200ms window of any HAProxy entry,
    so per-event timestamp correlation can't find them. Inheriting by
    session_id closes that gap. ADR-010, BUG 2 follow-up.

    A `matched_inherited` prior is itself inheritable — chaining is safe
    because all events in the chain trace back to the same primary
    timestamp match (via `pk = SESSION#<id>`).
    """
    resp = _DDB.query(
        TableName=TABLE_NAME,
        KeyConditionExpression="pk = :pk",
        FilterExpression="correlation_status IN (:m, :mi)",
        ExpressionAttributeValues={
            ":pk": {"S": f"SESSION#{session_id}"},
            ":m":  {"S": "matched"},
            ":mi": {"S": "matched_inherited"},
        },
        ProjectionExpression="src_ip",
        Limit=1,
    )
    items = resp.get("Items", [])
    if not items:
        return None
    return items[0].get("src_ip", {}).get("S")


def _process_cowrie_object(bucket: str, key: str) -> dict[str, int]:
    raw_events = _read_object_lines(bucket, key)
    stored: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    # Per-batch session→IP cache. Two roles:
    #   1. Avoid an extra DDB Query per event when many events share the
    #      same session within one batch (typical Cowrie shape: connect,
    #      version, kex, login, ... all under one session_id).
    #   2. Carry forward an in-batch primary match from the connect event
    #      to siblings without a DDB round-trip — the connect's match was
    #      written this batch and the sibling reads would miss it.
    # Sentinel "" means "looked up, no prior match found" — so we skip
    # the DDB query a second time for the same session within the batch.
    session_match_cache: dict[str, str] = {}
    for raw in raw_events:
        # Synthetic events ship country/asn/asn_org pre-baked. Strip those
        # before Cowrie-schema validation (the schema is extra="forbid"; the
        # Cowrie shape is canonical, the enrichment is ours). When present,
        # they take precedence over GeoIP lookup; absent, fall back to the
        # MaxMind layer.
        src_country = raw.pop("country", None)
        src_asn = raw.pop("asn", None)
        src_asn_org = raw.pop("asn_org", None)
        # fluent-bit's record_modifier filter stamps these for us. Drop them
        # before schema validation; they're transport metadata, not Cowrie
        # event fields.
        raw.pop("fluent_host", None)
        raw.pop("fluent_source", None)

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

        # Correlation: only run on session.connect events (the connection
        # boundary) and propagate the result to subsequent events in the
        # same session. For now, run on every event with src_ip=127.0.0.1
        # — Cowrie's loopback signature — which is the practical proxy for
        # "connection arrived through the tunnel."
        cowrie_src_ip = raw.get("src_ip", "")
        is_tunneled = cowrie_src_ip == "127.0.0.1"

        correlation_status: str | None = None
        candidate_count: int | None = None
        candidate_ips: list[str] | None = None
        resolved_src_ip = cowrie_src_ip
        if is_tunneled:
            session_id = raw.get("session", "")
            # Forward inheritance: try the per-session prior match first.
            # If a prior matched (or matched_inherited) event of this
            # session exists, inherit its src_ip. Skips the timestamp
            # window entirely. ADR-010, BUG 2 follow-up.
            inherited_ip: str | None = None
            if session_id:
                if session_id in session_match_cache:
                    cached = session_match_cache[session_id]
                    inherited_ip = cached or None
                else:
                    inherited_ip = _lookup_session_prior_match(session_id)
                    session_match_cache[session_id] = inherited_ip or ""
            if inherited_ip is not None:
                resolved_src_ip = inherited_ip
                correlation_status = "matched_inherited"
                candidate_count = 1
                candidate_ips = [inherited_ip]
                _emit_metric("BackwardCorrelationOutcomes", 1.0,
                             dimensions={"result": "inherited"})
            else:
                status, candidates = _correlate(raw["timestamp"])
                correlation_status = status
                candidate_count = len(candidates)
                candidate_ips = [c.client_ip for c in candidates] if candidates else []
                if status == "matched":
                    resolved_src_ip = candidates[0].client_ip
                    # Cache so siblings in the same batch inherit without a query.
                    if session_id:
                        session_match_cache[session_id] = resolved_src_ip

        # GeoIP runs on the post-correlation IP. ADR-010 — this is the change
        # that makes the GeoMap render real attacker geography even though
        # Cowrie sees only loopback.
        if src_country is not None:
            enrichment = GeoIPLookup(
                country=src_country,
                asn=int(src_asn) if src_asn is not None else None,
                asn_org=src_asn_org,
            )
        elif _ENRICHER is not None:
            enrichment = _ENRICHER.enrich(resolved_src_ip)
        else:
            enrichment = GeoIPLookup(country=None, asn=None, asn_org=None)

        stored_evt = _build_stored_event(
            raw,
            enrichment=enrichment,
            src_ip=resolved_src_ip,
            correlation_status=correlation_status,
            correlation_candidate_count=candidate_count,
            correlation_candidate_ips=candidate_ips,
        )
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


def _process_object(bucket: str, key: str) -> dict[str, int]:
    """Dispatch by S3 key prefix.

    `raw/haproxy/...` → HAProxy connection log (writes HAPROXY_CONN items).
    `raw/cowrie/...`  → Cowrie events with correlation.
    `raw/...`         → legacy synthetic path (Phase 7); still works
                        because synthetic Cowrie events carry their own
                        country/asn enrichment and their src_ip is not
                        127.0.0.1, so correlation is skipped.
    """
    if key.startswith("raw/haproxy/"):
        return _process_haproxy_object(bucket, key)
    return _process_cowrie_object(bucket, key)


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
        # S3 event notifications URL-encode the key — fluent-bit writes literal
        # `=` in `date=YYYY-MM-DD/host=pi/`, which arrives here as `%3D`.
        # boto3.get_object expects the unencoded form; decoding here is
        # standard for S3-event-driven Lambdas.
        key = urllib.parse.unquote_plus(key)
        result = _process_object(bucket, key)
        for k, v in result.items():
            totals[k] += v
        _log("object_processed", bucket=bucket, key=key, **result)

    _log("invocation_summary", **dict(totals))
    return dict(totals)
