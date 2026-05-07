from __future__ import annotations

import json
import logging
import os
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key
from pydantic import ValidationError

from functions.shared.api_dto import (
    BreakdownParams,
    BreakdownResponse,
    EventsParams,
    EventsResponse,
    HealthResponse,
    SessionEventsResponse,
    SummaryResponse,
    TimelineBucketRow,
    TimelineParams,
    TimelineResponse,
    TopAsnItem,
    TopAsnsParams,
    TopAsnsResponse,
    TopListItem,
    TopListParams,
    TopListResponse,
)
from functions.shared.ddb_helpers import (
    make_ddb_client_config,
    unmarshal_dynamodb_value,
)
from functions.shared.event_dto import PublicEvent, StoredEvent

logger = logging.getLogger("dram-soc.api")
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
GIT_SHA = os.environ.get("GIT_SHA", "unknown")
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "https://dashboard.dram-soc.org")
# ALLOWED_ORIGIN may be a single origin or a comma-separated allowlist
# The Lambda echoes back
# whichever origin in the allowlist matches the request's `Origin` header,
# so the browser sees a valid CORS response. The first entry is used as
# the default fallback when the request has no Origin header (e.g. curl).
ALLOWED_ORIGINS = tuple(o.strip() for o in ALLOWED_ORIGIN.split(",") if o.strip())
DEFAULT_ALLOWED_ORIGIN = ALLOWED_ORIGINS[0] if ALLOWED_ORIGINS else "https://dashboard.dram-soc.org"

_DDB_CONFIG = make_ddb_client_config(max_pool_connections=25)
_DDB_RESOURCE = boto3.resource("dynamodb", config=_DDB_CONFIG)
_DDB_CLIENT = boto3.client("dynamodb", config=_DDB_CONFIG)
_TABLE = _DDB_RESOURCE.Table(TABLE_NAME)

# Module-level executor so we don't pay thread-pool construction cost per
# request. boto3 Client is documented thread-safe; running ~24 DDB Queries
# in parallel collapses fan-out latency from sequential ~24xO(20ms) to
# wall-clock ~one-query (the slowest). The Client (not Resource) is what's
# called from inside the executor — see module docstring.
_DDB_QUERY_EXECUTOR = ThreadPoolExecutor(max_workers=10)


# --- Helpers ------------------------------------------------------------------


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _select_origin(request_origin: str | None) -> str:
    """Pick the response Access-Control-Allow-Origin value.

    Browsers reject `*` when credentials are involved and reject mismatched
    origins outright, so we echo back the request's Origin header iff it's
    in the allowlist. Unknown origin → default to the first allowlisted
    origin (mainly so non-browser tools like curl still get a sensible
    header; their CORS doesn't matter to the browser anyway).
    """
    if request_origin and request_origin in ALLOWED_ORIGINS:
        return request_origin
    return DEFAULT_ALLOWED_ORIGIN


def _cors_headers(*, cache_control: str = "no-cache") -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": DEFAULT_ALLOWED_ORIGIN,
        "Access-Control-Allow-Methods": "GET, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
        "Cache-Control": cache_control,
    }
    # Vary: Origin keeps shared caches (CloudFront, browsers) from poisoning
    # one origin's response onto another's request when the allowlist has
    # multiple entries.
    if len(ALLOWED_ORIGINS) > 1:
        headers["Vary"] = "Origin"
    return headers


def _resp(
    status_code: int,
    body: dict[str, Any],
    *,
    cache_control: str = "no-cache",
) -> dict[str, Any]:
    # Handlers always return the default origin in their headers; the
    # top-level dispatcher (`handler`) rewrites Access-Control-Allow-Origin
    # to match the request's Origin if it's in the allowlist. Keeping
    # the per-handler call sites unchanged is intentional — the alternative
    # (threading request_origin through 8 functions) would be invasive.
    return {
        "statusCode": status_code,
        "headers": _cors_headers(cache_control=cache_control),
        "body": json.dumps(body, default=str),
    }


def _err(status_code: int, message: str) -> dict[str, Any]:
    return _resp(status_code, {"error": message})


def _query_all(**kwargs: Any) -> list[dict[str, Any]]:
    """Run a paginated Query against the dashboard table. Returns all items."""
    out: list[dict[str, Any]] = []
    last_evaluated = None
    while True:
        if last_evaluated is not None:
            kwargs["ExclusiveStartKey"] = last_evaluated
        resp = _TABLE.query(**kwargs)
        out.extend(resp.get("Items", []))
        last_evaluated = resp.get("LastEvaluatedKey")
        if not last_evaluated:
            break
    return out


def _coerce_int(value: Any) -> int:
    """DDB items round-trip through Decimal; coerce defensively."""
    if value is None:
        return 0
    return int(value)


def _run_parallel(
    work_items: list[Any],
    fn: Callable[[Any], Any],
    *,
    label: str,
) -> tuple[list[Any], list[tuple[Any, Exception]]]:
    """Run `fn(item)` for each item in `work_items` in parallel.

    Returns ``(successes, failures)`` where successes preserves no order and
    failures is a list of ``(item, exc)``. One failed query never tanks the
    whole endpoint — partial results bubble up; the caller decides how to
    surface the gap.
    """
    successes: list[Any] = []
    failures: list[tuple[Any, Exception]] = []
    futures = {_DDB_QUERY_EXECUTOR.submit(fn, item): item for item in work_items}
    for fut in as_completed(futures):
        item = futures[fut]
        try:
            successes.append(fut.result())
        except Exception as exc:
            failures.append((item, exc))
            _log(label, error=type(exc).__name__, item=str(item))
    return successes, failures


# --- Per-route handlers -------------------------------------------------------


def _handle_healthz() -> dict[str, Any]:
    # CORRELATION_WINDOW_US is read from the ingest Lambda's environment
    # at the API Lambda's cold start — both Lambdas read the same env
    # var name, so this surfaces the value the API Lambda was deployed
    # with. If the two Lambdas drift, the dashboard reports the API
    # Lambda's view (which is what affects the response shape).
    correlation_window_us = int(os.environ.get("CORRELATION_WINDOW_US", "500000"))
    body = HealthResponse(
        status="ok",
        version=GIT_SHA,
        correlation_window_us=correlation_window_us,
    ).model_dump()
    return _resp(200, body)


def _handle_summary() -> dict[str, Any]:
    """Read today's SUMMARY#DAY rollup + the HEARTBEAT item. Two GetItems.

    The original implementation fanned out across 30 daily summaries +
    hour-bucket Query + yesterday's summary, totalling 32 reads. The fix
    is architectural: SUMMARY#DAY is the canonical rollup; everything in
    the response either comes from it or from HEARTBEAT.

    `last_1h` is reported as `0` until a SUMMARY#HOUR rollup item exists
    (Phase 11 follow-up). Adding a 3rd query for it would defeat the bug
    fix; the frontend can render `last_1h=0` as "—" if desired.
    """
    today = _now_utc().date().isoformat()

    # Two GetItems in parallel — independent reads, ~one-RTT latency.
    def _get(key_pair: tuple[str, str]) -> dict[str, Any]:
        return _TABLE.get_item(Key={"pk": key_pair[0], "sk": key_pair[1]}).get("Item", {})

    results, _failures = _run_parallel(
        [("SUMMARY#DAY", today), ("HEARTBEAT", "honeypot")],
        _get,
        label="summary_get_failed",
    )
    # results order is non-deterministic; tag by pk.
    today_summary: dict[str, Any] = {}
    heartbeat: dict[str, Any] = {}
    for item in results:
        if item.get("pk") == "SUMMARY#DAY":
            today_summary = item
        elif item.get("pk") == "HEARTBEAT":
            heartbeat = item

    total_events = _coerce_int(today_summary.get("total_events"))
    unique_ips = _coerce_int(today_summary.get("unique_ips"))

    body = SummaryResponse(
        total=total_events,
        last_24h=total_events,
        last_1h=0,
        unique_ips_24h=unique_ips,
        sensor_last_seen=heartbeat.get("last_event_ts"),
    ).model_dump()
    return _resp(200, body, cache_control="public, max-age=30, s-maxage=30")


def _client_query_paginate(pk_value: str) -> list[dict[str, Any]]:
    """Low-level Client Query against `pk = pk_value`, paginated, unmarshalled.

    Used from inside the ThreadPoolExecutor — the Client interface is
    documented thread-safe; the higher-level Resource interface is not.
    """
    out: list[dict[str, Any]] = []
    last_evaluated = None
    while True:
        kwargs: dict[str, Any] = {
            "TableName": TABLE_NAME,
            "KeyConditionExpression": "#pk = :pk",
            "ExpressionAttributeNames": {"#pk": "pk"},
            "ExpressionAttributeValues": {":pk": {"S": pk_value}},
        }
        if last_evaluated is not None:
            kwargs["ExclusiveStartKey"] = last_evaluated
        resp = _DDB_CLIENT.query(**kwargs)
        for raw in resp.get("Items", []):
            out.append({k: unmarshal_dynamodb_value(v) for k, v in raw.items()})
        last_evaluated = resp.get("LastEvaluatedKey")
        if not last_evaluated:
            break
    return out


def _client_get_item(pk: str, sk: str) -> dict[str, Any] | None:
    """Low-level Client GetItem against pk/sk, unmarshalled. None if missing."""
    resp = _DDB_CLIENT.get_item(
        TableName=TABLE_NAME,
        Key={"pk": {"S": pk}, "sk": {"S": sk}},
    )
    raw = resp.get("Item")
    if raw is None:
        return None
    return {k: unmarshal_dynamodb_value(v) for k, v in raw.items()}


def _query_one_hour_eventid_bucket(bucket_dt: datetime) -> TimelineBucketRow:
    bucket_str = bucket_dt.strftime("%Y-%m-%dT%H")
    items = _client_query_paginate(f"AGG#HOUR#{bucket_str}#eventid")
    count = sum(_coerce_int(it.get("count")) for it in items)
    return TimelineBucketRow(ts=bucket_dt.strftime("%Y-%m-%dT%H:00:00Z"), count=count)


def _query_one_day_summary(day_dt: datetime) -> TimelineBucketRow:
    day = day_dt.date().isoformat()
    item = _client_get_item("SUMMARY#DAY", day)
    count = _coerce_int(item.get("total_events")) if item else 0
    return TimelineBucketRow(ts=f"{day}T00:00:00Z", count=count)


def _handle_timeline(query: dict[str, str]) -> dict[str, Any]:
    try:
        params = TimelineParams.model_validate(query)
    except ValidationError as exc:
        return _err(400, f"invalid params: {exc.errors()}")

    window_hours = {"24h": 24, "7d": 24 * 7, "30d": 24 * 30}[params.window]
    now = _now_utc()

    if params.bucket == "1h":
        work = [now - timedelta(hours=offset) for offset in range(window_hours)]
        successes, failures = _run_parallel(
            work, _query_one_hour_eventid_bucket, label="timeline_query_failed"
        )
        # Each failure becomes an explicit gap with `count=None`.
        for bucket_dt, _exc in failures:
            successes.append(
                TimelineBucketRow(ts=bucket_dt.strftime("%Y-%m-%dT%H:00:00Z"), count=None)
            )
        buckets = sorted(successes, key=lambda b: b.ts)
    else:  # 1d
        days = max(1, window_hours // 24)
        work = [now - timedelta(days=offset) for offset in range(days)]
        successes, failures = _run_parallel(
            work, _query_one_day_summary, label="timeline_summary_failed"
        )
        for day_dt, _exc in failures:
            successes.append(
                TimelineBucketRow(ts=f"{day_dt.date().isoformat()}T00:00:00Z", count=None)
            )
        buckets = sorted(successes, key=lambda b: b.ts)

    body = TimelineResponse(buckets=buckets).model_dump()
    return _resp(200, body, cache_control="public, max-age=60, s-maxage=60")


def _query_rank(*, window: str, dimension: str, limit: int) -> list[dict[str, Any]]:
    """Query GSI3 for top-N rank items in (window, dimension)."""
    return _TABLE.query(
        IndexName="gsi3",
        KeyConditionExpression=Key("gsi3pk").eq(f"RANK#{window}#{dimension}"),
        Limit=limit,
    ).get("Items", [])


def _handle_top_list(dimension: str, query: dict[str, str]) -> dict[str, Any]:
    try:
        params = TopListParams.model_validate(query)
    except ValidationError as exc:
        return _err(400, f"invalid params: {exc.errors()}")
    window = "24H" if params.window == "24h" else "7D"
    rows = _query_rank(window=window, dimension=dimension, limit=params.limit)
    items = [TopListItem(value=str(it["value"]), count=_coerce_int(it.get("count"))) for it in rows]
    body = TopListResponse(items=items).model_dump()
    return _resp(200, body, cache_control="public, max-age=30, s-maxage=30")


def _handle_top_asns(query: dict[str, str]) -> dict[str, Any]:
    try:
        params = TopAsnsParams.model_validate(query)
    except ValidationError as exc:
        return _err(400, f"invalid params: {exc.errors()}")
    window = "24H" if params.window == "24h" else "7D"
    rows = _query_rank(window=window, dimension="asn", limit=params.limit)
    # The rank items only carry the ASN as `value`. ASN org is enrichment
    # we surface via a per-EVENT lookup if available; otherwise None.
    items: list[TopAsnItem] = []
    for it in rows:
        try:
            asn_int = int(it["value"])
        except (KeyError, ValueError):
            continue
        items.append(
            TopAsnItem(
                asn=asn_int,
                asn_org=None,
                count=_coerce_int(it.get("count")),
            )
        )
    body = TopAsnsResponse(items=items).model_dump()
    return _resp(200, body, cache_control="public, max-age=60, s-maxage=60")


def _handle_events(query: dict[str, str]) -> dict[str, Any]:
    try:
        params = EventsParams.model_validate(query)
    except ValidationError as exc:
        return _err(400, f"invalid params: {exc.errors()}")

    today_iso = _now_utc().date().isoformat()
    kwargs: dict[str, Any] = {
        "IndexName": "gsi2",
        "KeyConditionExpression": Key("gsi2pk").eq(f"DAY#{today_iso}"),
        "ScanIndexForward": False,  # newest first
        "Limit": params.limit,
        "FilterExpression": "#t = :event",
        "ExpressionAttributeNames": {"#t": "type"},
        "ExpressionAttributeValues": {":event": "EVENT"},
    }
    if params.before:
        # Look up everything strictly older than `before` (ISO 8601).
        # GSI2 sk format: "<ts>#SESSION#<sid>"; "<before>" sorts before any
        # timestamp at-or-after `before`, so the inequality holds.
        kwargs["KeyConditionExpression"] = Key("gsi2pk").eq(f"DAY#{today_iso}") & Key("gsi2sk").lt(
            params.before
        )

    resp = _TABLE.query(**kwargs)
    raw_items = resp.get("Items", [])

    public_events: list[PublicEvent] = []
    for raw in raw_items:
        # Build the PublicEvent via the StoredEvent → PublicEvent projection,
        # which drops password_raw. extra="forbid" on PublicEvent prevents
        # any raw item field from sneaking through.
        try:
            stored = StoredEvent.model_validate(raw)
        except ValidationError:
            # Defensive: a row that doesn't fit the schema gets skipped
            # rather than crashing the request. Logged sans any field values.
            _log("events_row_invalid", eventid=raw.get("eventid"))
            continue
        public_events.append(PublicEvent.from_stored(stored))

    next_before: str | None = None
    if len(public_events) >= params.limit and public_events:
        # The next page begins strictly before the oldest item we just sent.
        oldest = public_events[-1]
        next_before = oldest.ts

    body = EventsResponse(items=public_events, next_before=next_before).model_dump()
    return _resp(200, body, cache_control="public, max-age=15, s-maxage=15")


def _query_one_hour_technique_bucket(bucket_dt: datetime) -> dict[str, int]:
    bucket = bucket_dt.strftime("%Y-%m-%dT%H")
    items = _client_query_paginate(f"AGG#HOUR#{bucket}#technique")
    out: dict[str, int] = defaultdict(int)
    for it in items:
        out[str(it.get("value", "other"))] += _coerce_int(it.get("count"))
    return dict(out)


def _handle_breakdown(query: dict[str, str]) -> dict[str, Any]:
    try:
        params = BreakdownParams.model_validate(query)
    except ValidationError as exc:
        return _err(400, f"invalid params: {exc.errors()}")

    window_hours = 24 if params.window == "24h" else 24 * 7
    now = _now_utc()
    work = [now - timedelta(hours=offset) for offset in range(window_hours)]
    successes, _failures = _run_parallel(
        work, _query_one_hour_technique_bucket, label="breakdown_query_failed"
    )
    # Failed hours are silently skipped from the totals — no per-hour
    # field in the response, so a gap manifests as a slightly lower count.
    totals: dict[str, int] = defaultdict(int)
    for partial in successes:
        for tech, count in partial.items():
            totals[tech] += count

    body = BreakdownResponse(
        brute_force=totals.get("brute_force", 0),
        credential_stuffing=totals.get("credential_stuffing", 0),
        scanner=totals.get("scanner", 0),
        other=totals.get("other", 0),
    ).model_dump()
    return _resp(200, body, cache_control="public, max-age=60, s-maxage=60")


def _handle_session(session_id: str) -> dict[str, Any]:
    if not session_id:
        return _err(400, "session id required")
    raw_items = _query_all(KeyConditionExpression=Key("pk").eq(f"SESSION#{session_id}"))
    public_events: list[PublicEvent] = []
    for raw in raw_items:
        try:
            stored = StoredEvent.model_validate(raw)
        except ValidationError:
            _log("session_row_invalid", eventid=raw.get("eventid"))
            continue
        public_events.append(PublicEvent.from_stored(stored))

    body = SessionEventsResponse(events=public_events).model_dump()
    return _resp(200, body, cache_control="public, max-age=300, s-maxage=300")


# --- Dispatch -----------------------------------------------------------------


def _route(event: dict[str, Any]) -> dict[str, Any]:
    """Pure routing: returns the response shape with the default-origin headers."""
    route_key: str = event.get("routeKey") or ""
    path_params: dict[str, str] = event.get("pathParameters") or {}
    query_params: dict[str, str] = event.get("queryStringParameters") or {}

    _log("request", route=route_key)

    if route_key == "GET /api/healthz":
        return _handle_healthz()
    if route_key == "GET /api/summary":
        return _handle_summary()
    if route_key == "GET /api/timeline":
        return _handle_timeline(query_params)
    if route_key == "GET /api/top/{dimension}":
        dim = path_params.get("dimension") or ""
        # Explicit plural→singular map. The earlier `dim.rstrip("s")` was
        # latently broken for "countries" → "countrie" (rstrip strips every
        # trailing 's', not one; "-ies" pluralization needs a real lookup).
        DIMENSION_BY_ROUTE = {
            "usernames": "username",
            "passwords": "password",
            "countries": "country",
        }
        if dim == "asns":
            return _handle_top_asns(query_params)
        singular = DIMENSION_BY_ROUTE.get(dim)
        if singular is not None:
            return _handle_top_list(singular, query_params)
        return _err(404, f"unknown dimension: {dim}")
    if route_key == "GET /api/events":
        return _handle_events(query_params)
    if route_key == "GET /api/breakdown":
        return _handle_breakdown(query_params)
    if route_key == "GET /api/sessions/{id}":
        return _handle_session(path_params.get("id") or "")

    return _err(404, f"unknown route: {route_key}")


def _request_origin(event: dict[str, Any]) -> str | None:
    """Pull the Origin header from an APIGW v2 event. HTTP/2 lowercases names."""
    headers = event.get("headers") or {}
    return headers.get("origin") or headers.get("Origin")


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """API Gateway HTTP API → routeKey dispatch.

    routeKey examples:
      "GET /api/healthz"
      "GET /api/top/{dimension}"
      "GET /api/sessions/{id}"

    The dispatcher rewrites the response's Access-Control-Allow-Origin
    header to echo the request's Origin (if in the allowlist) so the
    Phase 8.5 apex + www origins can fetch alongside the dashboard
    subdomain. See ALLOWED_ORIGINS / _select_origin.
    """
    response = _route(event)
    request_origin = _request_origin(event)
    response["headers"]["Access-Control-Allow-Origin"] = _select_origin(request_origin)
    return response
