"""Aggregator Lambda — DynamoDB Streams + EventBridge schedules.

Three responsibilities, dispatched by the shape of the incoming event:

1. **Stream record processing** (DynamoDB Streams, NEW_IMAGE)
   For each new event item, atomically increment hourly counters via
   `UpdateExpression "ADD count :inc"` for each dimension we care about
   (username, password, country, asn, eventid). Technique counter only
   updates on `cowrie.session.closed` events — by then we have the session
   summary needed to classify.

2. **Rank rebuild** (EventBridge rate(1 minute), `{"action": "rank_rebuild"}`)
   Query the trailing 24h and 7d windows of AGG#HOUR# items, sum by value
   within each dimension, write the top-25 rank items per (window, dimension).
   Old rank items expire via TTL.

3. **Daily summary** (EventBridge cron(5 0 * * ? *), `{"action": "daily_summary"}`)
   Walk yesterday's events via GSI2 and write the SUMMARY#DAY item.

Idempotency (Fix E):
  - Per-record idempotency is enforced via the DEDUP#STREAM sentinel
    mechanism. ADD-increment alone is **not** idempotent (ADD +1 twice
    yields +2), so each stream record is deduplicated at the eventID
    level before any counter increments run. The first sighting of a
    given Streams `eventID` writes a sentinel `pk=DEDUP#STREAM, sk=<eventID>`
    with a conditional `attribute_not_exists(pk)` and TTL = +1h. A second
    sighting fails the conditional and the aggregator skips the record.
  - This defends against `BisectBatchOnFunctionError=true` partial-batch
    retries — when a batch fails partway through, AWS replays earlier
    records that already succeeded; the dedup sentinel catches them.
  - Streams retention is 24h max; partial-batch retries fire within
    seconds. 1h sentinel TTL gives massive safety margin without bloating
    storage.
  - We additionally skip stream records whose NEW_IMAGE has `type != EVENT`
    so aggregator-written items (AGG_COUNT, RANK, SUMMARY) don't recurse.
  - Rank rebuild is deterministic given the underlying counter state —
    running it twice produces the same RANK items (Fix A delete-then-write).
"""

from __future__ import annotations

import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from functions.shared.aggregate_dto import Dimension, RankWindow, rank_sk
from functions.shared.ddb_helpers import (
    make_ddb_client_config,
    unmarshal_dynamodb_value,
    unmarshal_image,
)
from functions.shared.technique_classifier import (
    SessionSummary,
    classify_session,
)

logger = logging.getLogger("dram-soc.aggregator")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))


def _log(event: str, /, **kwargs: Any) -> None:
    logger.info(json.dumps({"event": event, **kwargs}))


TABLE_NAME = os.environ.get("DDB_TABLE", "dram-soc-honeypot")
HOURLY_TTL_DAYS = int(os.environ.get("HOURLY_TTL_DAYS", "60"))
RANK_TTL_HOURS = int(os.environ.get("RANK_TTL_HOURS", "26"))
SUMMARY_TTL_DAYS = int(os.environ.get("SUMMARY_TTL_DAYS", "365"))
RANK_TOP_N = int(os.environ.get("RANK_TOP_N", "25"))
DEDUP_TTL_SECONDS = int(os.environ.get("DEDUP_TTL_SECONDS", "3600"))  # 1h, see Fix E
RANK_24H_HOURS = 24
RANK_7D_HOURS = 24 * 7

_DDB_CONFIG = make_ddb_client_config()
_DDB_CLIENT = boto3.client("dynamodb", config=_DDB_CONFIG)
_DDB_RESOURCE = boto3.resource("dynamodb", config=_DDB_CONFIG)
_TABLE = _DDB_RESOURCE.Table(TABLE_NAME)

# Dimensions promoted from each EVENT item into hourly counters.
# `technique` is computed only at session.closed time and handled separately.
_PER_EVENT_DIMENSIONS: tuple[Dimension, ...] = (
    "username",
    "password",
    "country",
    "asn",
    "eventid",
)

_RANKED_DIMENSIONS: tuple[Dimension, ...] = (
    "username",
    "password",
    "country",
    "asn",
    "technique",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hour_bucket(ts: str) -> str:
    """Turn an ISO 8601 timestamp into a YYYY-MM-DDTHH bucket key."""
    return ts[:13]


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _hourly_ttl(bucket: str) -> int:
    """Epoch seconds at which an hourly counter for `bucket` expires."""
    bucket_dt = datetime.fromisoformat(bucket + ":00:00+00:00")
    return int((bucket_dt + timedelta(days=HOURLY_TTL_DAYS)).timestamp())


def _rank_ttl() -> int:
    return int((_now_utc() + timedelta(hours=RANK_TTL_HOURS)).timestamp())


def _summary_ttl(day: str) -> int:
    day_dt = datetime.fromisoformat(day + "T00:00:00+00:00")
    return int((day_dt + timedelta(days=SUMMARY_TTL_DAYS)).timestamp())


# Backwards-compatibility shims — re-export the shared helpers under the
# leading-underscore names existing tests already import.
_unmarshal_dynamodb_value = unmarshal_dynamodb_value
_unmarshal_image = unmarshal_image


def _claim_event_id(event_id: str) -> bool:
    """Reserve a Streams eventID for processing. Returns True if this is the
    first time we've seen it, False if it's been processed before.

    Fix E — defends against BisectBatchOnFunctionError partial-batch retries
    that replay successfully-processed records when later records in the
    same batch fail. See module docstring.
    """
    ttl = int(datetime.now(timezone.utc).timestamp()) + DEDUP_TTL_SECONDS
    try:
        _TABLE.put_item(
            Item={
                "pk": "DEDUP#STREAM",
                "sk": event_id,
                "type": "DEDUP_SENTINEL",
                "ttl": ttl,
            },
            ConditionExpression="attribute_not_exists(pk)",
        )
        return True
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise


def _increment_counter(
    *, bucket: str, dimension: Dimension, value: str, delta: int = 1
) -> None:
    """Atomic ADD-increment of an AGG#HOUR# counter."""
    pk = f"AGG#HOUR#{bucket}#{dimension}"
    sk = f"VALUE#{value}"
    _TABLE.update_item(
        Key={"pk": pk, "sk": sk},
        UpdateExpression=(
            "ADD #c :inc "
            "SET #t = :type, #d = :dim, #v = :val, #b = :bucket, "
            "#ttl = if_not_exists(#ttl, :ttl)"
        ),
        ExpressionAttributeNames={
            "#c": "count",
            "#t": "type",
            "#d": "dimension",
            "#v": "value",
            "#b": "bucket",
            "#ttl": "ttl",
        },
        ExpressionAttributeValues={
            ":inc": delta,
            ":type": "AGG_COUNT",
            ":dim": dimension,
            ":val": value,
            ":bucket": bucket,
            ":ttl": _hourly_ttl(bucket),
        },
    )


def _process_event_item(item: dict[str, Any]) -> int:
    """Increment hourly counters for one EVENT item. Returns dimensions touched."""
    bucket = _hour_bucket(item["ts"])
    touched = 0
    for dim in _PER_EVENT_DIMENSIONS:
        value = item.get(dim)
        if value is None:
            continue
        # Counter values are strings in DDB; coerce here.
        _increment_counter(bucket=bucket, dimension=dim, value=str(value), delta=1)
        touched += 1

    # technique is per-session, computed on session.closed only
    if item.get("eventid") == "cowrie.session.closed":
        technique = _classify_session_for_event(item)
        if technique is not None:
            _increment_counter(
                bucket=bucket, dimension="technique", value=technique, delta=1
            )
            touched += 1
    return touched


def _classify_session_for_event(closed_event: dict[str, Any]) -> str | None:
    """Build a SessionSummary by querying the session's events, then classify.

    On `cowrie.session.closed` we re-Query the SESSION#<id> partition to
    reconstruct counts. This is one extra read per session, which at honeypot
    scale (~thousands/day) is negligible against on-demand DDB pricing.
    """
    session = closed_event.get("session")
    if not session:
        return None
    duration = float(closed_event.get("duration") or 0.0)
    resp = _TABLE.query(KeyConditionExpression=Key("pk").eq(f"SESSION#{session}"))
    items = resp.get("Items", [])
    failed = sum(1 for it in items if it.get("eventid") == "cowrie.login.failed")
    succ = sum(1 for it in items if it.get("eventid") == "cowrie.login.success")
    usernames = {
        it["username"]
        for it in items
        if it.get("eventid") in {"cowrie.login.failed", "cowrie.login.success"}
        and it.get("username") is not None
    }
    cmd_count = sum(1 for it in items if it.get("eventid") == "cowrie.command.input")
    summary = SessionSummary(
        duration_seconds=duration,
        login_failed_count=failed,
        login_success_count=succ,
        unique_usernames=len(usernames),
        command_count=cmd_count,
    )
    return classify_session(summary)


# ---------------------------------------------------------------------------
# Stream entry point
# ---------------------------------------------------------------------------


def _handle_stream_records(records: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts = defaultdict(int)
    for record in records:
        if record.get("eventName") not in {"INSERT", "MODIFY"}:
            counts["skipped"] += 1
            continue
        new_image = record.get("dynamodb", {}).get("NewImage")
        if not new_image:
            counts["skipped"] += 1
            continue
        item = _unmarshal_image(new_image)
        if item.get("type") != "EVENT":
            counts["skipped_non_event"] += 1
            continue
        # Fix E — per-record idempotency. Stream records always carry an
        # `eventID`; if it's missing (defensive) we still process to avoid
        # silently dropping data.
        event_id = record.get("eventID")
        if event_id is not None and not _claim_event_id(event_id):
            counts["skipped_duplicate"] += 1
            continue
        try:
            touched = _process_event_item(item)
            counts["processed"] += 1
            counts["dimensions_touched"] += touched
        except Exception as exc:  # noqa: BLE001
            counts["errors"] += 1
            _log(
                "stream_record_error",
                error=type(exc).__name__,
                eventid=item.get("eventid"),
                session=item.get("session"),
            )
            raise
    return dict(counts)


# ---------------------------------------------------------------------------
# Rank rebuild
# ---------------------------------------------------------------------------


def _query_hourly_counters_for_window(
    *, dimension: Dimension, window_hours: int, now: datetime | None = None
) -> dict[str, int]:
    """Sum AGG#HOUR# counters across the trailing `window_hours`."""
    now = now or _now_utc()
    totals: dict[str, int] = defaultdict(int)
    for offset in range(window_hours):
        bucket_dt = now - timedelta(hours=offset)
        bucket = bucket_dt.strftime("%Y-%m-%dT%H")
        pk = f"AGG#HOUR#{bucket}#{dimension}"
        last_evaluated = None
        while True:
            kwargs: dict[str, Any] = {"KeyConditionExpression": Key("pk").eq(pk)}
            if last_evaluated is not None:
                kwargs["ExclusiveStartKey"] = last_evaluated
            resp = _TABLE.query(**kwargs)
            for item in resp.get("Items", []):
                value = item.get("value")
                count = int(item.get("count") or 0)
                if value is None:
                    continue
                totals[value] += count
            last_evaluated = resp.get("LastEvaluatedKey")
            if not last_evaluated:
                break
    return totals


def _rebuild_rank_for(
    *, window: RankWindow, dimension: Dimension, now: datetime | None = None
) -> int:
    """Rebuild the top-N rank items for one (window, dimension).

    Delete-then-write semantics: the rank rows for a value carry the count
    in the sk (`rank_sk`), so when a value's count changes between rebuilds
    the new rebuild would write a fresh row with a different sk while the
    prior row still exists. To prevent this duplication, we query and
    delete every existing rank row for `pk = RANK#<window>#<dimension>`
    before writing the new top-N. The resulting state depends only on the
    current AGG#HOUR# state, so the operation is replay-safe.
    """
    window_hours = RANK_24H_HOURS if window == "24H" else RANK_7D_HOURS
    totals = _query_hourly_counters_for_window(
        dimension=dimension, window_hours=window_hours, now=now
    )
    pk = f"RANK#{window}#{dimension}"

    # 1. Find every existing rank row for this (window, dimension).
    existing_keys: list[dict[str, str]] = []
    last_evaluated = None
    while True:
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": Key("pk").eq(pk),
            "ProjectionExpression": "pk, sk",
        }
        if last_evaluated is not None:
            kwargs["ExclusiveStartKey"] = last_evaluated
        resp = _TABLE.query(**kwargs)
        for item in resp.get("Items", []):
            existing_keys.append({"pk": item["pk"], "sk": item["sk"]})
        last_evaluated = resp.get("LastEvaluatedKey")
        if not last_evaluated:
            break

    # 2. Delete the stale rows (any count). batch_writer auto-batches at 25.
    if existing_keys:
        with _TABLE.batch_writer() as batch:
            for key in existing_keys:
                batch.delete_item(Key=key)

    # 3. Write the new top-N.
    if not totals:
        return 0
    top_n = sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))[:RANK_TOP_N]
    ttl = _rank_ttl()
    written = 0
    with _TABLE.batch_writer() as batch:
        for value, count in top_n:
            sk = rank_sk(count, value)
            batch.put_item(
                Item={
                    "pk": pk,
                    "sk": sk,
                    "gsi3pk": pk,
                    "gsi3sk": sk,
                    "type": "RANK",
                    "window": window,
                    "dimension": dimension,
                    "value": value,
                    "count": count,
                    "ttl": ttl,
                }
            )
            written += 1
    return written


def _handle_rank_rebuild(now: datetime | None = None) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for window in ("24H", "7D"):
        for dim in _RANKED_DIMENSIONS:
            count = _rebuild_rank_for(window=window, dimension=dim, now=now)
            out[f"{window}#{dim}"] = count
    return dict(out)


# ---------------------------------------------------------------------------
# Daily summary
# ---------------------------------------------------------------------------


def _handle_daily_summary(now: datetime | None = None, *, target: str = "yesterday") -> dict[str, Any]:
    """Walk a day's events via GSI2 and write the SUMMARY#DAY item.

    `target`:
      - "yesterday" (default) — original 00:05 UTC cron behavior. Writes
        the canonical end-of-day rollup once the day is complete.
      - "today" — Phase 10 BUG 1 follow-up. Called by a 5-minute cron
        so /api/summary's GetItem on SUMMARY#DAY/<today> returns
        non-stale totals between the rollover crons. Same key, latest
        write wins; the 00:05 cron locks in yesterday's final value.
    """
    now = now or _now_utc()
    if target == "today":
        target_dt = now.date()
    else:
        target_dt = (now - timedelta(days=1)).date()
    day = target_dt.isoformat()
    gsi2pk = f"DAY#{day}"

    total_events = 0
    sessions: set[str] = set()
    src_ips: set[str] = set()
    successful_logins = 0
    file_downloads = 0
    techniques: dict[str, int] = defaultdict(int)

    last_evaluated = None
    while True:
        kwargs: dict[str, Any] = {
            "IndexName": "gsi2",
            "KeyConditionExpression": Key("gsi2pk").eq(gsi2pk),
        }
        if last_evaluated is not None:
            kwargs["ExclusiveStartKey"] = last_evaluated
        resp = _TABLE.query(**kwargs)
        for item in resp.get("Items", []):
            if item.get("type") != "EVENT":
                continue
            total_events += 1
            sessions.add(item.get("session", ""))
            src_ips.add(item.get("src_ip", ""))
            eid = item.get("eventid")
            if eid == "cowrie.login.success":
                successful_logins += 1
            elif eid == "cowrie.session.file_download":
                file_downloads += 1
        last_evaluated = resp.get("LastEvaluatedKey")
        if not last_evaluated:
            break

    # Technique counts via the AGG#HOUR# items from yesterday's 24 hourly buckets.
    for hour in range(24):
        bucket = f"{day}T{hour:02d}"
        pk = f"AGG#HOUR#{bucket}#technique"
        resp = _TABLE.query(KeyConditionExpression=Key("pk").eq(pk))
        for item in resp.get("Items", []):
            techniques[item["value"]] += int(item.get("count") or 0)

    sessions.discard("")
    src_ips.discard("")

    item = {
        "pk": "SUMMARY#DAY",
        "sk": day,
        "type": "SUMMARY",
        "day": day,
        "total_events": total_events,
        "unique_ips": len(src_ips),
        "unique_sessions": len(sessions),
        "successful_logins": successful_logins,
        "file_downloads": file_downloads,
        "techniques": dict(techniques),
        "ttl": _summary_ttl(day),
    }
    _TABLE.put_item(Item=item)
    return item


# ---------------------------------------------------------------------------
# Lambda dispatch
# ---------------------------------------------------------------------------


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Top-level entry point. Dispatches by event shape."""
    if "Records" in event and any(
        r.get("eventSource") == "aws:dynamodb" for r in event["Records"]
    ):
        result = _handle_stream_records(event["Records"])
        _log("stream_summary", **result)
        return result

    action = event.get("action")
    if action == "rank_rebuild":
        result = _handle_rank_rebuild()
        _log("rank_rebuild_summary", **result)
        return result

    if action == "daily_summary":
        result = _handle_daily_summary()
        _log("daily_summary_summary", day=result["day"],
             total_events=result["total_events"])
        return {"day": result["day"], "total_events": result["total_events"]}

    if action == "today_summary":
        # Phase 10 BUG 1 follow-up. Runs every 5 min so today's
        # SUMMARY#DAY rollup is near-real-time. Overwrites the same key
        # the 00:05 daily cron eventually finalizes.
        result = _handle_daily_summary(target="today")
        _log("today_summary_summary", day=result["day"],
             total_events=result["total_events"])
        return {"day": result["day"], "total_events": result["total_events"]}

    _log("unknown_event_shape", keys=list(event.keys()))
    return {"status": "no-op"}
