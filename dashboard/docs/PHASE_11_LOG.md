# Phase 11 — Real-data tuning buffer (log)

PROJECT_PLAN.md §11 anticipated Phase 11 as "the 3–5 days post-cutover when real-attack data exposes assumptions the synthetic path didn't." Phase 10's seven hotfixes (URL-decode, tz, schema-loosening, bidirectional + inheritance correlation, window widen, today_summary cron, GIT_SHA bump) were the immediate-blocker tier. Phase 11 is the next-tier-down quality work that surfaces only after a production data shape exists to grep against. Splitting into 11A (parser tuning) and 11B (CI/CD) per the operator's call.

## Phase 11A — Parser tuning + new aggregation dimensions

**Outcome:** real-data-driven schema relaxation + two new aggregation dimensions, locked behind 24 fixture-driven regression tests so future changes can't silently re-break the parser. Deployed 2026-05-07 19:14 UTC; `cowrie.client.kex` validation errors dropped from 48/hr to 0 within 3 minutes; first `command` AGG#HOUR# item (`uname`) appeared within 2 minutes from a real attacker.

### What changed

#### `functions/shared/cowrie_schema.py` — `extra="forbid"` → `extra="ignore"`

Cowrie 2.x ships per-version field churn the original schema didn't anticipate. Real-data observation found three failing eventids:

| Event | Extras schema rejected | Drop rate (pre-fix) |
|---|---|---|
| `cowrie.client.kex` | `hasshAlgorithms`, `langCS` | ~48/hr |
| `cowrie.session.params` | `arch`; also `message: []` (list shape) | ~6/hr |
| `cowrie.log.closed` | `ttylog`, `size`, `duplicate` | ~6/hr |

Switched `extra="forbid"` → `extra="ignore"`. The schema's safety net moved from "reject all unknowns" to "field-level validators stay strict" — timestamp format, IP format, port range, eventid pattern, `check_fields()` cross-field invariants. Documented explicitly in the model docstring so future maintainers don't infer "loose-extra" means "loose-everywhere."

Also widened `message: str | None` → `str | list | None` to accept `cowrie.session.params`'s occasional list-shape, mirrored on `StoredEvent` and `PublicEvent` so the ingest handler passes the value through without coercion. Frontend grep confirmed no component reads `event.message` today; TypeScript type stays `string | null` until Phase 12 (or whenever) surfaces it on the UI.

#### `functions/aggregator/handler.py` — two new synthetic dimensions

`_PER_EVENT_DIMENSIONS` is the generic per-field aggregation loop (username, password, country, asn, eventid). Two new dimensions don't fit that model because they apply only to specific eventid types AND derive their counter value (not a raw field copy):

- **`command`** — first whitespace-separated token of `input` for `cowrie.command.input` events. Bounds cardinality against bot-scanner probe traffic where `whoami`, `uname`, `cat`, `wget` dominate. Full attack input is preserved at the `EVENT#` row for forensics; aggregation surface uses the first token to keep the AGG#HOUR# space and signal visible.
- **`proxy_target_port`** — `dst_port` for `cowrie.direct-tcpip.{request,data}` events. Surfaces what services attackers are trying to proxy through (3478 STUN, 1080 SOCKS, 5060 SIP probes are common).

Both added to `_RANKED_DIMENSIONS` so the every-minute `rank_rebuild` cron writes their RANK# items immediately. Phase 12's `/api/top/{command,proxy_target_port}` endpoints will light up without an aggregator change.

#### `tests/backend/fixtures/{sanitize.py,real_data/*.json}` — real-attack fixtures

Captured 10 sanitized real Cowrie events (one per observed eventid: connect, version, kex, login.failed, login.success, command.input, session.closed, session.params, log.closed, direct-tcpip.request). `sanitize_for_fixture()` enforces the publishable-on-public-repo rules: ADR-005 `password_raw` strip, RFC 5737 doc-IP swap for the maintainer's home IP, geo-zero on country/asn/asn_org, fluent-bit transport-metadata strip, real attacker IPs preserved (already public via passive-DNS / threat-intel feeds).

#### Tests — 262/262 pass (was 233; +29 net)

- `test_real_fixture_round_trip.py` (NEW): 10 fixtures × 2 parametrized cases (validates clean + sanitization-leak guards) + 4 unit tests (list-message, log.closed extras, kex extras, fixtures dir populated)
- `test_aggregator_handler.py`: +5 cases (command happy-path, command-only-on-input-event, command-skips-empty, proxy_target_port happy-path, proxy_target_port-only-on-direct-tcpip)
- `test_cowrie_schema.py`: 1 test renamed (`test_extra_fields_rejected` → `test_extra_fields_silently_dropped`) reflecting the policy change

### Live verification (post-deploy)

- 19:14:37 UTC — ingest Lambda updated
- 19:15:29 UTC — aggregator Lambda updated
- 19:17:43 UTC — `event_invalid` filter for `cowrie.client.kex` returned 0 over the prior 3-min window (was 48/hr pre-deploy)
- 19:17:43 UTC — `AGG#HOUR#2026-05-07T19#command` partition contained `VALUE#uname count=1` — first real-attacker command captured under the new dimension
- `AGG#HOUR#2026-05-07T19#proxy_target_port` partition empty for the hour (no direct-tcpip attempts in the verification window — wiring confirmed by tests)

### Decisions

- **`extra="ignore"`** rather than maintaining an explicit allow-list of known Cowrie extras. The allow-list approach gets stale on every Cowrie point release and the per-list maintenance is exactly the overhead this fix removes. Field-level validators are the safety net.
- **First-token aggregation for `command`** rather than full-input aggregation. Full input lives on `EVENT#` rows for forensic drill-down; first-token aggregation surfaces the trend signal without exploding AGG#HOUR# cardinality.
- **`command`/`proxy_target_port` ranked immediately** rather than holding the rank-rebuild add for Phase 12. Rank-rebuild cost is rounding error ($0.0001/day in DDB on-demand); pre-ranking removes a backfill task at widget-time.
- **Real-data fixtures committed under `tests/backend/fixtures/real_data/`** rather than a separate package or external storage. Fixtures need to live with the tests that load them; sanitization makes them publishable. `sanitize_for_fixture()` is the canonical helper for future fixture grabs.

### Open follow-ups

- **TypeScript type drift on `event.message`** — Python widened to `str | list | None`; TS stays `string | null`. No runtime impact today (no frontend component reads `event.message`); will need a 1-line widen if/when Phase 12 surfaces it.
- **Phase 11B (CI/CD)** is the second prong — held until 11A ships clean. Plan covers 4 GitHub Actions workflows (CI on PR, tf-plan-on-PR comment, manual backend deploy, push-to-main frontend deploy) mirroring the Diamond IQ pattern, plus an `aws_iam_role.dram-soc-github-deploy` trust policy literal-copied from Diamond IQ's working version with one string changed.
- **Phase 12** — surface the new `command` + `proxy_target_port` dimensions on the dashboard. Pre-ranked data is already populating; widgets are ~30 min of frontend work.
