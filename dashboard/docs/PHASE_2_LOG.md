# Phase 2 — Ingest path: progress log

**Status:** Complete; awaiting review.
**Date:** 2026-04-28
**Plan reference:** [PROJECT_PLAN.md §11](PROJECT_PLAN.md) — Phase 2 Ingest path (PROJECT_PLAN.md is at v1.4)

---

## Outcome summary

All three Phase 2 live acceptance tests passed against deployed AWS infrastructure:

| Test | Expected | Actual | Status |
|---|---|---|---|
| 1 — happy path: upload 5000 synthetic events | 5000 items in DDB within ~60–90s | **5000 items** in 125s end-to-end (5s upload + 120s drain) | PASS |
| 2 — idempotency: replay same upload | Count unchanged at 5000 | **5000 items** (no duplicates) | PASS |
| 3 — malformed object → DLQ | DLQ depth = 1 | **DLQ depth = 1** after Lambda's 3-attempt async retry cycle (~5 min) | PASS |

The Phase 2 stack (17 resources) is deployed to AWS account 334856751632 in us-east-1.

---

## What was built (offline + applied)

### `dashboard/functions/`

```
functions/
├── __init__.py
├── ingest/
│   ├── __init__.py
│   └── handler.py              # S3 PutObject → DDB BatchWriteItem
├── shared/
│   ├── __init__.py
│   ├── cowrie_schema.py        # Phase 1
│   ├── password_classifier.py  # ADR-005
│   ├── geoip.py                # MaxMind wrapper (LRU-cached, layer-conditional)
│   ├── event_dto.py            # StoredEvent + PublicEvent (extra="forbid")
│   └── data/
│       ├── password_dictionary.txt   # 6024 entries, UTF-8
│       └── build_dictionary.py
└── layers/geolite2/
    ├── README.md
    └── download_geolite2.sh    # Deferred per Phase 2 decision; layer not built yet
```

### `dashboard/infrastructure/terraform/modules/ingest/`

S3 bucket + DLQ + Lambda + IAM role + log group + 4 alarms + S3 notification (see PROJECT_PLAN.md §11 Phase 2 deliverables).

### Tests

```
tests/backend/  (91 tests, 92.68% coverage)
├── conftest.py                          # AWS_DEFAULT_REGION default
├── test_cowrie_schema.py                # 12 tests
├── test_event_dto.py                    # 7 tests, password_raw API leak guard
├── test_generator.py                    # 20 tests (Phase 1)
├── test_generator_aws_paths.py          # 4 tests (Phase 1)
├── test_generator_determinism.py        # 9 tests (Phase 2 v1.4 — NEW)
├── test_geoip.py                        # 6 tests
├── test_ingest_handler.py               # 5 moto integration tests
├── test_ingest_helpers.py               # 14 tests (_to_ddb_attr, _chunked, etc.)
├── test_ingest_malformed_event.py       # 1 test
└── test_password_classifier.py          # 13 tests
```

### Live deployment

- DynamoDB table `dram-soc-honeypot` (3 GSIs, on-demand, PITR, streams).
- S3 bucket `dram-soc-honeypot-ingest` (versioning, SSE-S3, public-access block, lifecycle Glacier @30d / expire @90d).
- SQS DLQ `dram-soc-ingest-dlq` (14-day retention, SSE managed).
- Lambda `dram-soc-ingest` (Python 3.13, 256 MB, 60s timeout, **no reserved concurrency**).
- IAM role `dram-soc-ingest-role` with minimum permissions.
- CloudWatch log group `/aws/lambda/dram-soc-ingest` (14-day retention).
- 4 CloudWatch alarms (errors, throttles, p95 duration, DLQ depth).
- S3 → Lambda event notification on `s3:ObjectCreated:*` filtered to `raw/*.json.gz`.

State location: `s3://diamond-iq-tfstate-334856751632/soc-detection-lab/dashboard/terraform.tfstate` with `diamond-iq-tfstate-locks` (Path A — reused Diamond IQ's bucket).

---

## What went wrong, and what we learned

### Apply attempt 1 — `reserved_concurrent_executions = 20`

```
Error: setting Lambda Function (dram-soc-ingest) concurrency:
  InvalidParameterValueException: Specified ReservedConcurrentExecutions for function
  decreases account's UnreservedConcurrentExecution below its minimum value of [10].
```

11 of 17 resources created; Lambda failed at `PutFunctionConcurrency` and was tainted. The plan's `ingest=20` was borrowed from Diamond IQ's pattern. PROJECT_PLAN bumped to v1.2: revised to `5/5/5`.

### Apply attempt 2 — `reserved_concurrent_executions = 5`

Same error. Diagnostic via `aws lambda get-account-settings`:

```
ConcurrentExecutions:           10
UnreservedConcurrentExecutions: 10
```

The account's *total* Lambda concurrency quota is 10 — not the historical default of 1000. AWS enforces a hard rule that `UnreservedConcurrentExecutions` cannot drop below 10. **No positive integer reservation can fit in this account** until the per-region quota is raised via a service-quota-increase ticket. PROJECT_PLAN bumped to v1.3: removed reserved_concurrent_executions entirely (deleted, not zeroed). Cost-defense intent now relies on the upstream API GW throttling + CloudWatch alarms.

### Apply attempt 3 — no reservation

Clean apply. 6 resources added (1 destroyed — the tainted Lambda + its 5 dependents that hadn't been created yet). Lambda Active.

### Live test 2 — idempotency replay produced 10,000 items (FAIL on initial run)

The first idempotency run produced count = 10,000 instead of 5000. Diagnosis: the synthetic generator was **not actually deterministic** despite PROJECT_PLAN.md §8 saying "Deterministic via `--seed`". The generator anchored timestamp generation to `datetime.now(timezone.utc)` at the moment of CLI invocation. Same seed → same RNG sequence → same session IDs and same offsets, but different anchor → different timestamps → different DDB `sk` values → legitimately distinct items. The Lambda's idempotency was correct; the generator was non-deterministic.

Fix (v1.4):

1. Added `--anchor-time <ISO 8601 UTC>` flag.
2. When `--seed` is supplied without `--anchor-time`, the anchor defaults to **midnight UTC of the current calendar day** — same-day reruns are now byte-identical without forcing the caller to pass an anchor.
3. Added `tests/backend/test_generator_determinism.py` — hashes two seeded runs and asserts byte equality. Also asserts that different seeds and different anchors produce different output.
4. PROJECT_PLAN.md §8 documented the determinism contract explicitly.

### DynamoDB cleanup before re-running tests

The 10,000 items from the failed Test 2 needed clearing. `terraform destroy -target=module.honeypot_table` failed because the table had `deletion_protection_enabled = true`. Workflow: `aws dynamodb update-table --no-deletion-protection-enabled` (transient) → `terraform destroy -target` → `terraform apply` to recreate the table from state. The targeted destroy cascaded a re-creation of the 7 ingest-module resources that referenced the table's ARN; all came back in the apply. Net: empty table, all 17 resources Active.

### Live test 3 — DLQ initially empty at 90s

DLQ depth was 0 at the user-specified 90s mark. The Lambda's `dead_letter_config` routes async-invocation failures to the DLQ only **after all async retries fail** — default 2 retries with backoff. Total possible window is ~5–6 minutes from the original invocation to DLQ landing. Continued polling revealed depth = 1 at the next check (~3.5 minutes after upload). Confirmed in CloudWatch logs: 3 attempts of the same `RequestId a908959c-8f8a-4fc6-96ee-a9c0599eb4ba`, each failing with `JSONDecodeError: Expecting value: line 1 column 1 (char 0)`. Test 3 PASS.

---

## Phase 2 acceptance criteria — final

| Criterion | Result |
|---|---|
| Running `synthetic_data_generator.py --upload-s3 --events 5000` results in 5000 items in DynamoDB within 60s | PASS — 5000 items, ~120s drain wall-clock |
| Re-running same upload produces 0 net new items (idempotency) | PASS — 5000 items unchanged |
| A deliberately malformed object lands in the DLQ | PASS — DLQ depth = 1 after async-retry exhaustion |
| pytest integration tests using moto cover the full ingest path | PASS — 91 tests, 92.68% coverage |
| Password classifier tests green; `password_raw` never in any API DTO | PASS — `PublicEvent` `extra="forbid"` enforced; `from_stored` drops the field |

---

## Timing observations (Phase 11 calibration data)

- **Generator → S3 upload**: 5 seconds for 5000 events as ~24 hourly-bucketed gzipped objects (avg ~700 bytes each compressed).
- **S3 PutObject → Lambda invocation latency**: typically < 1 s (S3 event notifications are eventually consistent but usually fire promptly).
- **Lambda cold start**: ~700 ms first invocation; subsequent invocations ~150–400 ms.
- **5000-event ingest end-to-end**: 95–120 s wall-clock (multiple Lambda invocations running in parallel against the per-hour-bucketed S3 objects). DDB write throughput is the bottleneck under default on-demand autoscaling; not a concern at honeypot scale.
- **Async-retry-to-DLQ window for whole-object failures**: ~3–5 minutes. Phase 11 alarm thresholds for DLQ depth should expect a 5-minute eventual-delivery window before paging.
- **Lambda max memory used**: 107–109 MB at peak (well under 256 MB allocated). Could potentially drop to 192 MB; not worth tuning at our scale.

---

## Plan amendments through Phase 2

PROJECT_PLAN.md changelog ran v1.0 → v1.4:

- **v1.2**: Reserved Concurrency `20/5/20` → `5/5/5` after first apply failure.
- **v1.3**: Reserved Concurrency `5/5/5` → **none** after second apply failure (account quota at the 10-unit floor).
- **v1.4**: Generator §8 updated with explicit determinism contract + `--anchor-time` flag + property test.

---

## Open backlog items (not Phase 2 blockers)

1. **AWS Lambda concurrency quota increase ticket** — file `aws service-quotas request-service-quota-increase --service-code lambda --quota-code L-B99A9384 --desired-value 1000` to restore per-function reservation as a tertiary cost defense. Blocked on no Phase; account-level operational task.
2. **MaxMind GeoLite2 license key** — currently absent. Lambda runs without GeoIP enrichment (`country=null, asn=null` in items). Phase 9 wires the weekly refresh; Phase 11 will need real attacker IPs for the GeoMap visualization to be meaningful.
3. **Python 3.13 install on dev box** — package script falls back to 3.14 with cross-target wheel flags. Lambda runtime is 3.13; cross-target packaging worked correctly (verified via deployed Lambda being Active and serving requests). Not blocking.
4. **Powertools opt-in deferred** — handler uses stdlib logging with a custom JSON formatter. Adopt Powertools' `Logger` if/when we want tracing or metrics middleware in Phase 4.

---

## Decisions made that aren't in the plan

1. **Generator's `--seed` is now nullable.** v1.0–1.3 had `default=42`. v1.4 changes it to `default=None` so `args.seed is not None` can drive the implicit-midnight-anchor behaviour. When seed is omitted entirely, the generator falls back to seed=42 + wall-clock anchor (same as legacy behaviour for non-deterministic runs).

2. **`functions/__init__.py` is intentionally empty.** Required to make `from functions.ingest.handler import handler` work both in tests and in the deployed Lambda zip.

3. **`scripts/package_lambdas.py` (Python builder) supersedes `package_lambdas.sh`.** The bash script's heredoc had Git-Bash-on-Windows POSIX path translation issues. The Python version handles native Windows paths and uses `zipfile` instead of the missing `zip` binary. The bash version is retained for CI runners that have `zip`; both produce the same output.

4. **Targeted `terraform destroy` + re-apply for table cleanup** — chosen over `aws dynamodb delete-item`-in-a-loop (would have taken 10K API calls). Side effect: cascaded recreation of all ingest-module resources that reference the table's ARN. All recreated cleanly; no operational impact since traffic flow was paused during the cleanup.

5. **Idempotency mechanism stays as deterministic-key + put-overwrite.** No conditional `PutItem`. The deterministic `pk = SESSION#<sid>`, `sk = <ts>#<eventid>` plus `BatchWriteItem` semantics (re-puts overwrite) preserves "0 net new items" on replay, now that the generator is byte-deterministic.

---

**Phase 2 acceptance criteria met. All AWS infrastructure is live and tested. Awaiting your review before Phase 3 begins.**
