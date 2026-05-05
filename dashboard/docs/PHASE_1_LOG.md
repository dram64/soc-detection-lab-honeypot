# Phase 1 — Foundations: progress log

**Status:** Complete; awaiting review.
**Date:** 2026-04-28
**Plan reference:** [PROJECT_PLAN.md §11](PROJECT_PLAN.md) — Phase 1 Foundations

---

## What was built

### Directory scaffold (per PROJECT_PLAN.md §16)

```
dashboard/
├── docs/
│   ├── PROJECT_PLAN.md              (already present, v1.1)
│   ├── PHASE_1_LOG.md               (this file)
│   ├── adr/                         (7 ADRs landed; see below)
│   └── runbooks/                    (empty; runbooks land in their respective phases)
├── infrastructure/
│   └── terraform/
│       ├── README.md                (bootstrap recipe + phase status)
│       ├── environments/dev/        (versions, providers, backend, variables, main, outputs)
│       └── modules/
│           ├── dynamodb/            (Phase 1 — built)
│           ├── lambda/              (stub, Phase 2/3/4)
│           ├── api-gateway/         (stub, Phase 4)
│           ├── cloudfront/          (stub, Phase 8)
│           └── alarms/              (stub, Phase 9)
├── functions/
│   ├── ingest/                      (empty; Phase 2)
│   ├── api/                         (empty; Phase 4)
│   ├── aggregator/                  (empty; Phase 3)
│   └── shared/
│       ├── __init__.py
│       └── cowrie_schema.py         (Pydantic v2 models, ADR-001)
├── frontend/                        (empty; Phase 5)
├── frontend-apex/                   (empty; Phase 8.5)
├── tools/
│   ├── synthetic_data_generator.py  (Phase 1 — built)
│   └── data/
│       ├── usernames.txt            (~140 entries, ADR-001/PROJECT_PLAN.md §8)
│       ├── passwords.txt            (~600 entries — synthetic-traffic dictionary, ADR-005)
│       └── asn_pools.json           (16 ASN pools, weighted, ADR-001)
├── tests/
│   ├── backend/                     (test_cowrie_schema, test_generator, test_generator_aws_paths)
│   ├── frontend/                    (empty; Phase 5)
│   └── fixtures/                    (empty; populated on demand by generator)
└── pyproject.toml                   (ruff + mypy + pytest + coverage gate at 90%)
```

### ADRs landed
- ADR-001 — Cowrie event schema as canonical data model.
- ADR-002 — Pi → S3 → Lambda log shipping.
- ADR-003 — DynamoDB single-table design.
- ADR-004 — Frontend stack (React 18 + Vite + TS + TanStack Query + Tailwind).
- ADR-005 — Attempted-password dictionary filtering.
- ADR-007 — Cloudflare proxied DNS as edge WAF (no AWS WAF).
- ADR-009 — Captured-malware policy (SHA + URL only; no binary retention).

ADR-006 (GeoIP enrichment) and ADR-008 (Phase 10 cutover decision) deliberately deferred — they belong to their own phases per PROJECT_PLAN.md §11.

### Top-level repo edits (per PROJECT_PLAN.md §16)
- `.gitignore` — appended dashboard-scoped ignore patterns. **No other top-level files modified.**

---

## Acceptance criteria — results

### `terraform plan` clean (1 resource to add)

`terraform fmt -check -recursive` → clean.
`terraform init -backend=false` → clean.
`terraform validate` → `Success! The configuration is valid.`
`terraform plan` (dry-run with provider creds bypass for Phase 1; see "Deviations" below) → **`Plan: 1 to add, 0 to change, 0 to destroy.`**

The single resource is `module.honeypot_table.aws_dynamodb_table.honeypot`:
- `name = "dram-soc-honeypot"` ✓ prefix per §11
- 8 string attributes (pk, sk, gsi1pk/sk, gsi2pk/sk, gsi3pk/sk) ✓
- 3 GSIs (gsi1, gsi2, gsi3), all `projection_type = "ALL"` ✓
- `billing_mode = "PAY_PER_REQUEST"` ✓ ADR-003
- `stream_enabled = true`, `stream_view_type = "NEW_IMAGE"` ✓
- `point_in_time_recovery.enabled = true` ✓
- `ttl { attribute_name = "ttl", enabled = true }` ✓
- `server_side_encryption.enabled = true` ✓
- `deletion_protection_enabled = true` ✓
- Tags: `Project=soc-detection-lab`, `Component=dashboard`, `Environment=dev`, `ManagedBy=terraform` ✓

Outputs: `honeypot_table_name`, `honeypot_table_arn`, `honeypot_stream_arn` ✓

Full plan output captured during validation; nothing surprising.

### Generator produces 1000 valid Cowrie events

```
$ python tools/synthetic_data_generator.py --events 1000 --days 1 --out /tmp/phase1_smoke/ --seed 42
wrote 1000 events across 2 files to /tmp/phase1_smoke
```

All 1000 events validated against `CowrieEvent` Pydantic model — both `model_validate_json` and `check_fields()` (cross-field invariants) pass.

### Pytest 90%+ coverage on the generator module

```
36 passed in 1.68 s
Required test coverage of 90.0% reached. Total coverage: 97.18%

functions/shared/cowrie_schema.py      71 stmts   95% covered
tools/synthetic_data_generator.py     262 stmts   98% covered
TOTAL                                  333 stmts  97% covered
```

Remaining uncovered lines are non-control-flow defensive returns and an `if __name__ == "__main__"` guard already in coverage's exclude list. No control flow is uncovered.

### DynamoDB schema visible in plan output

Confirmed (see plan excerpt above). Not applied per Phase 1 hard-stop.

---

## Deviations from the plan

1. **Python version: 3.14 instead of 3.13.**
   The plan called for Python 3.13. The local machine has Python 3.12 and 3.14 installed; 3.13 is not available. The `pyproject.toml` constraint `requires-python = ">=3.13"` is satisfied by 3.14. No code in the generator or schema depends on 3.13-specific behaviour. Not flagged as a blocker. Recommend installing Python 3.13 before Phase 2 starts to match Lambda runtime targets exactly.

2. **AWS provider pinned to `< 6.0.0`.**
   The plan didn't specify a provider major version. The newly-released v6.0.0 deprecates `hash_key` / `range_key` on `aws_dynamodb_table` in favour of nested `key_schema` blocks, which would make the module configuration awkward to write while still being widely-documented in v5 form. Pinned both the module and the dev environment to `>= 5.50.0, < 6.0.0` to avoid the deprecation churn during Phase 1. Phase 2/3 can revisit when the v6 syntax is stable across all the resources we'll touch. Note: `version = ">= 5.50.0, < 6.0.0"` is in `versions.tf` for both the module and the dev env.

3. **`terraform plan` was run with provider credential validation skipped.**
   The Phase 1 acceptance criterion is "`terraform plan` is clean" (PROJECT_PLAN.md §11). Running plan against the real backend requires (a) AWS credentials and (b) the bootstrap S3 state bucket + DynamoDB lock table to exist. Per the user's Phase 1 instructions, the bootstrap is held as a "one-time manual step I'll review separately before Phase 2." To produce plan output without performing the bootstrap, I temporarily layered a `providers_override.tf` file (now removed; not committed) that set `skip_credentials_validation = true`, `skip_metadata_api_check = true`, `skip_requesting_account_id = true`, with placeholder access/secret keys. The plan was generated against this config with the S3 backend swapped out for the implicit local backend (also reverted). The actual `providers.tf`, `backend.tf`, and `versions.tf` committed to the repo are unchanged from their authored form. The plan output is faithful to what a real `terraform plan` will produce once the bootstrap is performed.

4. **Synthetic data generator uses Python 3.14 in the dev venv.**
   `dashboard/.venv/` was created locally for the test run; it is in `.gitignore` and not committed.

5. **Synthetic password dictionary in `tools/data/passwords.txt`.**
   Contains ~600 common-attack-dictionary entries. These are the same kind of strings as SecLists `Common-Credentials/` and similar public lists; they're attacker-traffic dictionary entries, not user secrets. Documented inline by their use site (the generator's session-builder).

6. **Generator's `inject_to_dynamodb` was patched mid-Phase to convert `float` → `Decimal`.**
   moto-backed test surfaced a real bug: boto3's DynamoDB resource interface rejects native Python floats. Cowrie's `duration` field is a float. Fix: a small `_to_ddb` recursive coercer at the write boundary. This is genuinely a Phase 2 concern (the ingest Lambda will need the same coercion) — the fix here is local to the generator's direct-inject path. Phase 2 will reuse the same pattern in `functions/shared/`.

---

## Open questions surfaced during Phase 1

1. **Bootstrap S3 + DynamoDB-lock for Terraform state.**
   The bootstrap commands are documented in `dashboard/infrastructure/terraform/README.md`. Confirm you want me to run the bootstrap before Phase 2 starts, or whether you'll run them yourself and hand me back the bucket + table names.

2. **Python 3.13 install on the dev box.**
   See deviation #1. Want me to install 3.13 via `winget`/Microsoft Store before Phase 2 (so `lambda` zip targets that runtime exactly), or stay on 3.14? AWS Lambda's `python3.13` runtime exists but `python3.14` is not yet a Lambda runtime — the Lambda packaging in Phase 2 will need 3.13 specifically.

3. **`functions/shared/data/password_dictionary.txt`** (the production dictionary used by the ingest Lambda's password classifier per ADR-005) does **not** yet exist. It lands in Phase 2's deliverables. Phase 1 only included `tools/data/passwords.txt` (the *synthetic-traffic* dictionary used by the generator to simulate attacker behaviour). These are deliberately separate files: the generator produces synthetic attacker traffic; the classifier decides which attempted passwords are dictionary hits. They may end up identical in content, but should remain physically separate so the dashboard's "what counts as a known-bad-dictionary password" decision is editable independent of the synthetic harness.

4. **GSI names: `gsi1` / `gsi2` / `gsi3` vs more semantic names** (`by-ip`, `by-day`, `by-rank`).
   I used the numeric form to match Diamond IQ's convention. If you'd prefer semantic GSI names, this is the cheapest moment to change them — no Lambda/API code references them yet.

---

## Decisions made that aren't in the plan

1. **GSI naming convention: `gsi1` / `gsi2` / `gsi3`.**
   See open question 4 above.

2. **Tags applied via the AWS provider's `default_tags` instead of per-resource.**
   Cleaner; every resource the dashboard creates inherits Project/Component/Environment/ManagedBy without per-module duplication. The DynamoDB module still accepts a `tags` map so module-specific overrides are possible if ever needed.

3. **Single-environment `dev/` folder for Terraform.**
   The plan gave the option of multiple environments in `infrastructure/terraform/environments/`. Phase 1 only built `dev/`. A `prod/` clone is a half-day's work in any future phase if needed. For a portfolio dashboard with one operator, two environments is overkill.

4. **`pyproject.toml` pins coverage `fail_under = 90` at the project level.**
   This makes the coverage gate enforced by `pytest` rather than by an external CI config, so it works locally too. CI in Phase 1 doesn't yet invoke pytest — that wires up in Phase 2 when `dashboard-tests.yml` lands.

5. **`.venv/` lives at `dashboard/.venv/` not at repo root.**
   Already covered by the `.gitignore` rule `dashboard/**/.venv/`.

---

## What is NOT done (and is correctly out of Phase 1 scope)

- AWS resources created — no `terraform apply` was run.
- OIDC IAM roles `dashboard-backend-deploy` / `dashboard-frontend-deploy` — Phase 2/4/8.
- Terraform state bootstrap (S3 + DDB lock) — held for separate review.
- Lambda functions (ingest, aggregator, api) — Phase 2/3/4.
- Frontend code — Phase 5.
- CloudFront, ACM, Cloudflare wiring — Phase 8.
- Apex landing page — Phase 8.5.
- Alarms, runbooks for viral-traffic / heartbeat — Phase 9.
- Pi shipper service — Phase 10.

---

**Phase 1 acceptance criteria met. Awaiting your review before Phase 2 begins.**
