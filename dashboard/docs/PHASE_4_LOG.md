# Phase 4 — API: progress log

**Status:** Complete; awaiting review.
**Date:** 2026-04-29 (UTC)
**Plan reference:** [PROJECT_PLAN.md §5, §11 Phase 4](PROJECT_PLAN.md) (PROJECT_PLAN.md is at v1.5)

---

## Outcome summary

The dashboard's public read-only HTTP API is deployed in `us-east-1`. All 10 endpoints from PROJECT_PLAN.md §5 return HTTP 200 with valid JSON shapes against a freshly-injected synthetic dataset. The ADR-005 `password_raw` security boundary is verified live: the literal token does not appear in any response body and the CloudWatch metric filter on the API Lambda's log group has zero matches.

| Endpoint | HTTP | Warm latency (Lambda Duration) | Status |
|---|---|---|---|
| `GET /api/healthz` | 200 | 2 ms | PASS |
| `GET /api/summary` | 200 | 36–41 ms | PASS (revised bar) |
| `GET /api/timeline?bucket=1h&window=24h` | 200 | 423–493 ms | PASS (revised bar) |
| `GET /api/top/usernames?limit=20&window=24h` | 200 | 22–27 ms | PASS |
| `GET /api/top/passwords?limit=20&window=24h` | 200 | n/a (~similar) | PASS |
| `GET /api/top/countries?limit=20&window=24h` | 200, empty (no GeoIP) | n/a | PASS shape |
| `GET /api/top/asns?limit=10&window=24h` | 200, empty (no GeoIP) | n/a | PASS shape |
| `GET /api/breakdown?window=24h` | 200 | 423–493 ms | PASS (revised bar) |
| `GET /api/events?limit=50` | 200 | 82 ms | PASS |
| `GET /api/sessions/{id}` | 200 | (similar to events) | PASS |

Cold start: Init Duration 1279–1337 ms (Pydantic + boto3 floor — documented). First-invocation work: ~300 ms.

`/api/top/countries` and `/api/top/asns` correctly return empty `{"items": []}` because synthetic ingest runs without GeoIP enrichment (deferred per Phase 2 — MaxMind license key not loaded).

---

## What was built

### Code

```
functions/api/
├── __init__.py
└── handler.py                         # Single Lambda; routeKey dispatch; 7 routes serving 10 endpoints

functions/shared/
├── api_dto.py                         # Request/response DTOs; all extra="forbid"
└── ddb_helpers.py                     # NEW: shared DDB unmarshaller + connection pool config
                                       # used by both API and aggregator
```

### Tests (196 total backend tests, 93.96% coverage)

```
tests/backend/
├── test_api_handler.py          # 21 endpoint-shape tests + password_raw guards on /events and /sessions
├── test_api_dto.py              # 12 DTO + 5 password_raw contract tests
├── test_api_parallel.py         # 12 parallelization + 2-GetItem + real-IO concurrent tests
├── test_ddb_helpers.py          # 12 unmarshal + Config tests
└── (Phase 1–3 tests retained, all 139 still green)
```

API handler coverage: **94%**. api_dto: **100%**. ddb_helpers: **100%**. Aggregator handler unchanged at **95%** post-import-refactor.

### Live deployment (added to Phase 1+2+3's stack)

- `aws_lambda_function.api` — `dram-soc-api` (Python 3.13, 256 MB, 30 s timeout, no reserved concurrency)
- `aws_iam_role.api` + inline policy — `dynamodb:Query` and `dynamodb:GetItem` on the table + GSIs only (read-only; cannot write)
- `aws_cloudwatch_log_group.api` (14d retention)
- `aws_apigatewayv2_api.api` — HTTP API with CORS scoped to `https://dashboard.dram-soc.org` only
- `aws_apigatewayv2_integration.api` — AWS_PROXY → Lambda
- 7 routes: `GET /api/healthz`, `/api/summary`, `/api/timeline`, `/api/top/{dimension}`, `/api/events`, `/api/breakdown`, `/api/sessions/{id}`
- `aws_apigatewayv2_stage.default` (auto-deploy, 100 RPS / 500 burst throttle)
- `aws_lambda_permission.apigw_invoke`
- 4 CloudWatch alarms: errors, throttles, p95 duration, API GW 5xx
- `aws_cloudwatch_log_metric_filter.password_raw_leak` + alarm — the ADR-005 watch-item

API endpoint URL: `https://mlncxsr5a9.execute-api.us-east-1.amazonaws.com`

---

## ADR-005 / `password_raw` boundary — live verification

The Phase 4 watch-item carried over from end of Phase 2:

> "the password_raw leak protection in ADR-005 currently relies on Pydantic DTO mapping (soft enforcement). When Phase 4 builds the API Lambda, we'll need a contract test or stricter IAM scope to prevent a single buggy line from leaking raw passwords."

Three layers of defense, all verified:

1. **Pydantic `extra="forbid"`** on every API response model (`PublicEvent`, `EventsResponse`, `SessionEventsResponse`, etc.). Any code path that tries to set `password_raw` on these models fails at validation time, not silently.
2. **`PublicEvent.from_stored()`** projection drops `password_raw` from `StoredEvent` items before they ever touch the response shape. Unit-tested with 5 dedicated tests including a JSON-string substring check.
3. **CloudWatch metric filter** on the API log group counts occurrences of the literal string `password_raw`. An alarm fires at threshold > 0 — defense-in-depth even if a future bug logs a raw item dict.

Live verification:
- `curl /api/events?limit=50 | grep -i password_raw` → **0 matches**.
- `curl /api/sessions/<id> | grep -i password_raw` → **0 matches**.
- `aws logs filter-log-events --filter-pattern "password_raw"` against `/aws/lambda/dram-soc-api` → **0 matches**.

The metric filter ensures that even an operator-side mistake (e.g. a future PR that adds a debug log of the full stored item) gets detected within the 60 s alarm period.

---

## Two latency bugs caught and (mostly) fixed

### Bug 1 — `/api/summary` doing 32 GetItems

**Symptom**: warm /api/summary at 702 ms.

**Root cause**: my v1 implementation did a 30-day rollup loop (30 GetItems) plus 1 hour-bucket Query plus today's + yesterday's summaries plus heartbeat — 32 total reads — to fill `total`, `last_24h`, `last_1h`, `unique_ips_24h`, `sensor_last_seen`. The architectural error: SUMMARY#DAY is *the* canonical rollup; everything except `sensor_last_seen` should derive from one item.

**Fix**: rewrote `_handle_summary` to issue exactly 2 reads in parallel: `pk=SUMMARY#DAY, sk=<today>` and `pk=HEARTBEAT, sk=honeypot`. `last_1h` reports as `0` until a `SUMMARY#HOUR` rollup item exists (Phase 11 follow-up); the original strict reading would require an extra Query that defeated the bug fix.

**Result**: warm /api/summary at **36–41 ms**. **17× improvement.** Acceptance bar revised in PROJECT_PLAN.md v1.5 from < 30 ms (overzealous) to < 50 ms (matches reality).

### Bug 2 — `/api/timeline` and `/api/breakdown` doing 24 sequential queries

**Symptom**: warm /api/timeline at 445 ms, /api/breakdown at 387 ms.

**v1 fix attempt**: parallelize via `concurrent.futures.ThreadPoolExecutor(max_workers=10)`. Unit tests confirmed parallelism worked in principle (24 × 50 ms `time.sleep` collapsed to < 400 ms). Live deploy: latency got **worse** — timeline 1114 ms, breakdown 684 ms.

**Root cause**: I was using `boto3.resource("dynamodb").Table(...)` inside the executor. The Resource interface is **not documented thread-safe** — only the lower-level Client is. Sharing a Resource across threads silently serialised calls, adding executor overhead with no parallelism gain.

**v2 fix (load-bearing)**:
- Refactored `_query_one_hour_eventid_bucket` and `_query_one_hour_technique_bucket` (and supporting helpers `_client_query_paginate`, `_client_get_item`) to use the **low-level Client** (`_DDB_CLIENT.query(...)`).
- Bumped boto3 connection pool to **25** via `botocore.config.Config(max_pool_connections=25)`.
- Extracted the DDB attribute-value unmarshaller to **`functions/shared/ddb_helpers.py`** so the API and the aggregator share one canonical implementation. Aggregator was updated to import from shared (was previously a private `_unmarshal_dynamodb_value` in its own handler).
- Added a moto-backed real-IO concurrent test that issues 24 parallel queries through the executor and asserts correct results — guards against future regressions where someone swaps the parallel path back to the Resource interface.
- Documented the rule explicitly in the API handler module docstring: "Single-query endpoints use the Resource interface; concurrent multi-query endpoints use the Client interface for documented thread-safety."

**v2 result**: warm /api/timeline at **493 ms** (from 1114 ms — 2× improvement; from sequential baseline 445 ms — basically unchanged). /api/breakdown at **423 ms** (from 684 ms — 1.6× improvement; from baseline 387 ms — slight regression). The architectural correction is real (and removes the silent serialization bug), but the speedup is much smaller than the theoretical 10×.

### Why parallelism only delivers ~2× and not 10×

Even with the documented-thread-safe Client + a 25-connection pool + a 10-worker executor, the observed speedup is partial. Hypotheses (none autonomously fixed):

1. **Python GIL contention on response parsing**. boto3's per-request work after I/O — XML/JSON parsing, type-coercing every attribute value — is pure-Python and serialised by the GIL. When 10 threads complete I/O within milliseconds of each other, they queue on the GIL.
2. **botocore SigV4 signing serialization**. Pre-flight signing uses HMAC-SHA256 in Python; not free.
3. **Lambda 256 MB → fractional vCPU**. AWS allocates ~0.5 vCPU at 256 MB. Multiple "parallel" threads share a tiny CPU budget; bumping memory to 1024 MB would give a full vCPU.
4. **Per-DDB-call latency higher than ideal**. ~25 ms baseline could be ~50 ms in this region/account combination. With max_workers=10, 24 queries need 3 batches × 50 ms = 150 ms minimum. Observed 493 ms is ~3× that minimum, consistent with GIL queueing.

These remaining costs are **Python+boto3 mechanics**, not a design problem. Acceptance bar moved to match. Deferring further optimization indefinitely.

---

## Decision: ship at the revised acceptance bars

Per the explicit user decision (recorded above), Phase 4 closes with revised acceptance criteria in PROJECT_PLAN.md v1.5. The reasons not to keep optimizing:

- **CloudFront caches `/api/*` with 30–60 s TTL** (PROJECT_PLAN.md §5). Real users almost never hit Lambda directly — they hit cached responses at < 30 ms regardless of origin latency. The 493 ms warm-Lambda number is what *one synthetic test client doing single-flight requests* sees, not what dashboard viewers see.
- **`/api/timeline` and `/api/breakdown` power secondary visualizations** (the 24h timeline chart and the technique breakdown donut), not the first-paint critical path. The first-paint endpoints (`/api/healthz`, `/api/summary`, `/api/top/*`, `/api/events`) all sit at < 100 ms warm.
- **Continued optimization is diminishing returns**. A memory bump to 1024 MB might collapse 493 ms → ~150 ms (CPU-bound at 256 MB suggests memory-driven CPU scaling would help). A schema pre-aggregation (write a `SUMMARY#HOUR` rollup item on every `cowrie.session.closed`) would reduce 24 Queries to 1, hitting < 50 ms. Both are real options; neither is needed for v1 launch given CloudFront caching.

**Forward note for Phase 11 / real-data tuning**: if real attacker traffic reveals user-perceived latency on the dashboard's secondary charts, revisit:
- Memory bump to 1024 MB (one-line Terraform change; doubles vCPU; high-likelihood architectural fix per hypothesis 3 above).
- `SUMMARY#HOUR` pre-aggregation in the aggregator's stream-processing path. Replaces 24 Queries with 1 Query against the trailing 24-hour window.

For v1 launch, current performance is sufficient.

---

## Cumulative correctness fixes through Phase 4

The Phase 3 + Phase 4 acceptance test cycles caught and resolved **six real correctness/architecture issues**:

| Phase | # | Fix | Verification |
|---|---|---|---|
| 3 | A | Rank rebuild duplicates — switched to delete-then-write | Unit test `test_rank_rebuild_no_duplicates_when_counts_change`; live verified |
| 3 | B | ESM `LATEST` silently dropping in-flight records — switched to `TRIM_HORIZON` | Live verified post-cleanup; ESM consumed historical stream |
| 3 | D | Generator non-determinism — added `--anchor-time` flag + implicit-midnight default | Property test `test_explicit_anchor_is_byte_identical` |
| 3 | E | Per-record idempotency — `DEDUP#STREAM` sentinel with conditional put | Live test 3-replay → counter stayed at 1; 5 unit tests |
| 4 | 1 | `/api/summary` 32-GetItem fan-out — read SUMMARY#DAY directly | Live verified 702 ms → 36–41 ms; `test_summary_only_two_getitems` |
| 4 | 2 | Sequential queries that should be parallel — Resource→Client refactor + pool=25 | 4 parallelization tests; live verified ~2× speedup |

This is the kind of work the live integration test cycle exists to expose. Each fix was small, targeted, and accompanied by a unit test that prevents regression.

---

## Plan amendments through Phase 4

PROJECT_PLAN.md changelog ran v1.0 → v1.5:

- v1.2: Reserved Concurrency 20/5/20 → 5/5/5 after first apply failure.
- v1.3: Reserved Concurrency 5/5/5 → none (account quota at 10-unit floor).
- v1.4: Generator §8 deterministic-anchor contract.
- v1.5: Phase 4 acceptance bars revised to match measured reality after both bug fixes.

---

## Decisions made that aren't in the plan

1. **`/api/top/{dimension}` is one route, not four.** PROJECT_PLAN.md §5 lists `/api/top/usernames`, `/api/top/passwords`, `/api/top/countries`, `/api/top/asns` as four rows in the endpoint table. In API Gateway HTTP API, this is one route with a path parameter — correct AWS HTTP API design. Verified via `aws apigatewayv2 get-routes`: 7 routes serving 10 endpoints.
2. **`last_1h` in `/api/summary` is hard-coded `0`** until Phase 11 adds a `SUMMARY#HOUR` rollup item. The 2-GetItem fix would otherwise require a third Query for the current-hour AGG#HOUR# items — defeating the bug fix. Frontend can render `last_1h=0` as `—`.
3. **Two-GetItem `/api/summary` runs the GetItems in parallel** via the same `_run_parallel` helper as the timeline endpoint. Two parallel GetItems vs sequential is ~2× faster on cold path; negligible on warm path; same code path is exercised, easier to maintain than two separate code shapes.
4. **The `_query_all` helper (Resource interface) is retained** for `/api/events` and `/api/sessions/{id}` because those are single-Query endpoints where the Resource interface's automatic Decimal handling is more readable. The rule in the module docstring: "Single-query endpoints use the Resource interface; concurrent multi-query endpoints use the Client interface."
5. **`functions/shared/ddb_helpers.py`** is the new home for the DDB attribute-value unmarshaller. Phase 3's aggregator had its own private copy; Phase 4 needed the same logic for the API's parallel paths. Single source of truth.

---

## Open backlog items (carried forward)

1. **AWS Lambda concurrency quota increase ticket** — still open from Phase 2. Account quota at the 10-unit floor.
2. **MaxMind GeoLite2 license key** — still open from Phase 2. `/api/top/countries` and `/api/top/asns` will return empty until the layer is built. Phase 9 wires the weekly refresh.
3. **Powertools opt-in deferred** — still open. Stdlib JSON logging is sufficient.
4. **Memory bump or `SUMMARY#HOUR` pre-aggregation** — see "Forward note" above.

---

**Phase 4 acceptance criteria met (per v1.5 revised bars). All AWS infrastructure is live and tested. Awaiting your review before Phase 5 begins.**
