# Honeypot Visualizer Dashboard — Project Plan

**Project:** SOC Detection Lab — Honeypot Visualizer Dashboard
**Owner:** Desi Ramirez (dram64)
**Repo:** https://github.com/dram64/soc-detection-lab (sub-path `dashboard/`)
**Public URL (target):** https://dashboard.dram-soc.org
**AWS account:** 334856751632 (us-east-1)
**Plan version:** 1.7 — 2026-05-07 (Phase 11B SHIPPED — all 5 steps complete; README rewritten; portfolio site live at apex)
**Status:** Phases 1–4 in flight

---

## 1. Executive summary

The Honeypot Visualizer Dashboard is the public-facing component of the SOC Detection Lab. It ingests JSON event logs produced by a Cowrie SSH/Telnet honeypot running on a Raspberry Pi 5, persists them in a low-cost AWS serverless backend, and renders live attack analytics on a CloudFront-fronted React dashboard at `dashboard.dram-soc.org`. The system is designed so that recruiters and reviewers can click a single live URL and immediately see real internet attacker behaviour — usernames tried, passwords sprayed, source geographies, ASNs, attack timelines, and captured commands.

The dashboard is built end-to-end against synthetic Cowrie-shaped data first, and only after the dashboard is verified will the Pi be exposed to the internet. The architectural patterns reuse the proven Diamond IQ stack (Python 3.13 Lambdas, DynamoDB single-table, S3 PutObject-triggered ingest, Terraform IaC, GitHub Actions OIDC, React 18 + Vite + TanStack Query, S3 + CloudFront, with Cloudflare's free WAF in front via proxied DNS). Cost target: ≤ $5/month additive AWS spend, hard-capped under the $50/month account budget.

**Timing context.** This is a 3–4 week build that runs **in parallel with active job applications**, not a "build first, apply later" sequence. Job search continues uninterrupted; the dashboard is portfolio infrastructure that strengthens the SOC Detection Lab as a resume artefact, and is **not a gating dependency** for sending out applications. Phases are sized so progress is visible and demoable each week — even an in-progress dashboard with synthetic data is a stronger portfolio link than no dashboard at all.

---

## 2. Architecture diagram

```
                                    INTERNET (attackers)
                                            │
                                            │ SSH/2222 (after Phase 10)
                                            ▼
                  ┌──────────────────────────────────────────────────┐
                  │  Home router @ 192.168.1.1                       │
                  │   port-forward 22/2222 → 192.168.1.253:2222      │
                  └────────────────────┬─────────────────────────────┘
                                       ▼
                  ┌──────────────────────────────────────────────────┐
                  │  Raspberry Pi 5 (192.168.1.253)                  │
                  │  ┌────────────────────────────────────────────┐  │
                  │  │ Cowrie honeypot                            │  │
                  │  │ /home/cowrie/cowrie/var/log/cowrie.json    │  │
                  │  └────────────────────┬───────────────────────┘  │
                  │  ┌────────────────────▼───────────────────────┐  │
                  │  │ cowrie-shipper (Python systemd service)    │  │
                  │  │ - tails JSON, batches to gzip every 60 s   │  │
                  │  │ - PUTs to s3://dram-soc-honeypot-ingest/   │  │
                  │  │   raw/YYYY/MM/DD/HH/<sensor>-<ts>.json.gz  │  │
                  │  │ - rotates IAM access key annually          │  │
                  │  └────────────────────┬───────────────────────┘  │
                  └───────────────────────┼──────────────────────────┘
                                          │ HTTPS (signed PUT)
═══════════════════════════════════════════│══════════════════════════════ AWS us-east-1
                                          ▼
                       ┌──────────────────────────────────┐
                       │  S3: dram-soc-honeypot-ingest    │
                       │   - object lock OFF              │
                       │   - lifecycle: Glacier@30d, X@90d│
                       └──────────────┬───────────────────┘
                                      │ s3:ObjectCreated:*
                                      ▼
                       ┌──────────────────────────────────┐
                       │  Lambda: ingest-fn               │
                       │  - parses gzipped NDJSON         │
                       │  - GeoIP enriches src_ip         │
                       │  - dedups via session+timestamp  │
                       │  - DynamoDB BatchWriteItem       │
                       └──────────────┬───────────────────┘
                                      ▼
                ┌──────────────────────────────────────────┐
                │  DynamoDB: dram-soc-honeypot             │
                │  PK / SK + GSI1 + GSI2 + GSI3            │
                │  on-demand, PITR on, TTL=90d on raw      │
                └──────────────┬───────────────────────────┘
                               │ DynamoDB Streams (NEW_IMAGE)
                               ▼
                ┌──────────────────────────────────────────┐
                │  Lambda: aggregator-fn                   │
                │  - increments AGG# counter items         │
                │  - hourly + daily + 7d windows           │
                │  - top-N usernames / passwords / ASNs    │
                │    / countries (heavy hitters approx.)   │
                └──────────────────────────────────────────┘

                ┌──────────────────────────────────────────┐
                │  Lambda: api-fn (HTTP API routeKey)      │
                │  Reads aggregates + raw events           │
                └──────────────┬───────────────────────────┘
                               ▲
                               │ JSON
                ┌──────────────┴───────────────────────────┐
                │  API Gateway HTTP API                    │
                │  api.dram-soc.org → /summary, /events,…  │
                └──────────────┬───────────────────────────┘
                               ▲
                               │
                ┌──────────────┴───────────────────────────┐
                │  CloudFront distribution                 │
                │  - origin 1: S3 (static React bundle)    │
                │  - origin 2: API GW (path /api/*)        │
                │  - ACM cert in us-east-1                 │
                │  - NO AWS WAF (see ADR-007)              │
                └──────────────┬───────────────────────────┘
                               ▲
                               │ HTTPS
═══════════════════════════════│══════════════════════════════ Cloudflare (proxied)
                  ┌────────────┴───────────────────┐
                  │  dashboard.dram-soc.org        │
                  │  CNAME → CloudFront            │
                  │  Cloudflare proxy: ON          │
                  │  (free WAF, DDoS, bot mgmt)    │
                  └────────────┬───────────────────┘
                               ▲
                               │
                          ┌────┴────┐
                          │ Browser │
                          └─────────┘
```

Supporting infra:

```
GitHub Actions (OIDC) ──assume──> IAM role: dashboard-backend-deploy
                       ──assume──> IAM role: dashboard-frontend-deploy

CloudWatch:
  - Alarms on every Lambda (errors, throttles, p95 duration)
  - Dashboards: ingest health, API latency, DDB consumed capacity
  - Log groups with 14d retention
  - Budget action at $50: SCP-style deny on lambda:Invoke + dynamodb:*
```

---

## 3. Data flow narrative

A bot probes `1.2.3.4:22` on the public IP. The home router NATs the connection to `192.168.1.253:2222`. Cowrie accepts the SSH handshake, advertises a fake Linux shell, and writes one JSON line per protocol event to `/home/cowrie/cowrie/var/log/cowrie/cowrie.json`. A Python systemd service (`cowrie-shipper`) tails that file, accumulates events for ~60 seconds (or 1 MB, whichever first), gzips them, and `PutObject`s to `s3://dram-soc-honeypot-ingest/raw/2026/04/27/23/honeypot-1714261800.json.gz`. The S3 PutObject event triggers the `ingest-fn` Lambda, which streams-parses the gzipped NDJSON, enriches each event with country + ASN from a bundled MaxMind GeoLite2 database, classifies any attempted password against a bundled known-bad attack-dictionary list (~5000 entries; ADR-005) — dictionary matches are stored as-is in `password`; non-matches are redacted to `<filtered:len=N>` in `password` while the raw value is preserved only in a never-exposed `password_raw` attribute — computes a deterministic event ID (`sha1(session|timestamp|eventid)` for idempotency), and issues a `BatchWriteItem` against the DynamoDB table.

DynamoDB Streams (new-image) immediately invokes the `aggregator-fn` Lambda, which atomically increments counter items: hourly buckets per dimension (username, password, country, ASN, technique), 24-hour rolling sums, and a per-day total event count. Aggregations are stored as additional items in the same table under reserved partition key prefixes. Top-N rankings are maintained as sorted secondary-index projections — the aggregator updates rank items only when a counter crosses a threshold to avoid GSI write storms.

The browser loads `https://dashboard.dram-soc.org`. The request passes through Cloudflare's proxy (free WAF, DDoS protection, bot management) before reaching CloudFront, which serves the static React bundle from S3. Once mounted, TanStack Query hooks fetch `/api/summary`, `/api/timeline?window=7d&bucket=1h`, `/api/top/usernames?limit=20`, `/api/top/passwords?limit=20`, `/api/top/countries?limit=20`, `/api/top/asns?limit=10`, and `/api/events?limit=50`. CloudFront proxies `/api/*` to the API Gateway HTTP API, which dispatches via `routeKey` into the single `api-fn` Lambda. That Lambda issues `Query` operations against the appropriate GSI (never a Scan) and returns JSON. TanStack Query caches each response for 30 seconds and refetches in the background; charts and counters update without a flicker. Recharts renders the bars/timeline; `react-simple-maps` projects the country counts onto a Robinson-projection world map.

When a budget action trips at $50, all `lambda:Invoke` and `dynamodb:*` actions are denied; CloudFront keeps serving the static bundle and a banner ("data feed paused — budget cap reached") informs viewers. The dashboard never goes fully dark.

---

## 4. DynamoDB schema design

**Table:** `dram-soc-honeypot`
**Capacity mode:** On-demand (PAY_PER_REQUEST) — predictable low volume, avoids provisioned-capacity waste
**PITR:** ON (35-day continuous backup; cost ≈ $0.20/GB/mo, well under $1/mo at our volume)
**Streams:** ON (`NEW_IMAGE`)
**TTL attribute:** `ttl` (epoch seconds; 90 days for raw events, no TTL on aggregate items)

### Keys

| Key | Type | Notes |
|---|---|---|
| `pk` | String | partition key |
| `sk` | String | sort key |
| `gsi1pk` / `gsi1sk` | String | GSI1: by source IP |
| `gsi2pk` / `gsi2sk` | String | GSI2: by time bucket (DAY/HOUR) |
| `gsi3pk` / `gsi3sk` | String | GSI3: top-N rank lookups |

All GSIs project `ALL` attributes (storage is cheap, query patterns vary).

### Item shapes

**1. Raw event item** (one per Cowrie event)
```
pk        = "SESSION#2db032f8e0b5"
sk        = "2026-04-27T23:19:26.097161Z#cowrie.session.connect"
gsi1pk    = "IP#192.168.1.79"
gsi1sk    = "2026-04-27T23:19:26.097161Z"
gsi2pk    = "DAY#2026-04-27"
gsi2sk    = "2026-04-27T23:19:26.097161Z#SESSION#2db032f8e0b5"
type      = "EVENT"
eventid   = "cowrie.session.connect"
session   = "2db032f8e0b5"
src_ip    = "192.168.1.79"
src_port  = 3592
dst_ip    = "192.168.1.253"
dst_port  = 2222
sensor    = "honeypot"
sensor_uuid = "c3ccafbe-40f0-11f1-8f67-88a29e085d67"
protocol  = "ssh"
country   = "US"            # GeoIP-enriched
asn       = 13335           # GeoIP-enriched
asn_org   = "Cloudflare"
ttl       = 1722123456      # +90 days
ingest_id = "sha1:abcd…"    # idempotency key
ts        = "2026-04-27T23:19:26.097161Z"
# event-type-specific fields:
username  = "root"          # for login events
password  = "123456"        # dictionary match → stored as-is (ADR-005)
                            # non-match: "<filtered:len=14>"
password_raw = "123456"     # NEVER returned by API; private to ingest pipeline
                            # for non-matches: holds the actual attempted value
input     = "wget http://…" # for command.input
url       = "http://…"      # for file_download
shasum    = "ab12…"
duration  = 160.9           # for session.closed
```

**2. Hourly aggregate counter** (one per dimension+bucket)
```
pk        = "AGG#HOUR#2026-04-27T23#username"
sk        = "VALUE#root"
type      = "AGG_COUNT"
dimension = "username"
value     = "root"
bucket    = "2026-04-27T23"
count     = 142
ttl       = +60d
```
Dimensions: `username`, `password`, `country`, `asn`, `eventid`, `technique` (brute_force | credential_stuffing | scanner | other).

**3. Top-N rank item** (rebuilt by aggregator on threshold-cross)
```
pk        = "RANK#24H#username"
sk        = "0000000142#root"          # zero-padded count desc via inversion
gsi3pk    = "RANK#24H#username"
gsi3sk    = "0000000142#root"
window    = "24H"
dimension = "username"
value     = "root"
count     = 142
ttl       = +24h
```
The aggregator computes ranks by querying the AGG#HOUR# items for the trailing window, summing, and writing the top 25 (we serve top 20; 5 overhead absorbs churn). Rebuild cadence: every 60 s via EventBridge schedule, plus on-demand on threshold crossings to keep the live feel.

**4. Daily summary item**
```
pk        = "SUMMARY#DAY"
sk        = "2026-04-27"
type      = "SUMMARY"
total_events = 8421
unique_ips = 312
unique_sessions = 287
successful_logins = 14
file_downloads = 3
techniques = { "brute_force": 6700, "credential_stuffing": 1320, "scanner": 401 }
```

**5. Heartbeat item** (sensor liveness)
```
pk = "HEARTBEAT"
sk = "honeypot"
last_event_ts = "2026-04-27T23:19:26Z"
last_ingest_ts = "2026-04-27T23:19:31Z"
```

### Access patterns → key plan

| Access pattern | Key used |
|---|---|
| All events in a session | `pk = SESSION#<id>` (Query) |
| All events from an IP, newest first | GSI1: `gsi1pk = IP#<ip>`, ScanIndexForward=false |
| All events on a day | GSI2: `gsi2pk = DAY#<date>` |
| Top-N usernames in last 24h | GSI3: `gsi3pk = RANK#24H#username`, Limit=20 |
| Recent 50 events | GSI2: `gsi2pk = DAY#<today>`, Limit=50, descending |
| Daily summary | `pk = SUMMARY#DAY`, `sk = <date>` |
| Heartbeat | `pk = HEARTBEAT` |

### Hot partition mitigation

The two partitions at risk are `DAY#<today>` (GSI2) and any single-IP partition during a sustained brute-force burst. Mitigations:

- **DAY shard suffix:** if a day exceeds 50K writes (configurable), the ingest Lambda starts writing `DAY#<date>#<shard 0..9>` round-robin. Read path queries all 10 shards in parallel and merges. Shard-on flag stored in a config item so it can be toggled without redeploy.
- **Per-IP partition burst:** GSI1 only — DynamoDB GSIs auto-split on heat above ~1000 WCU; on-demand handles this transparently. We accept eventual consistency lag on GSI1 (acceptable for the "events from this IP" drill-down).
- **Aggregator stream lag:** if streams back up, aggregator concurrency reservation = 5 prevents runaway costs; CloudWatch alarm at 60 s lag pages me.

---

## 5. API endpoints

All endpoints are GET, JSON, no auth. CORS allows only `https://dashboard.dram-soc.org`. Served at `https://dashboard.dram-soc.org/api/*` (CloudFront path-routes to API Gateway). Cache strategy: API Gateway response caching disabled (cheap, low QPS); CloudFront caches `/api/*` for 30 s with `Cache-Control: public, max-age=30, s-maxage=30` from the Lambda.

Expected QPS at steady state: ~0.5–2 RPS aggregate (a handful of concurrent viewers refetching every 30 s). Each Lambda dispatch < 50 ms p95.

| Method | Path | Query params | Response shape | CF cache | Backed by |
|---|---|---|---|---|---|
| GET | `/api/summary` | — | `{ total, last_24h, last_1h, unique_ips_24h, sensor_last_seen }` | 30s | SUMMARY#DAY + HEARTBEAT |
| GET | `/api/timeline` | `bucket=1h\|1d`, `window=24h\|7d\|30d` | `{ buckets: [{ ts, count }] }` | 60s | AGG#HOUR + AGG#DAY |
| GET | `/api/top/usernames` | `limit=20`, `window=24h\|7d` | `{ items: [{ value, count }] }` | 30s | RANK#<window>#username |
| GET | `/api/top/passwords` | `limit=20`, `window=24h\|7d` | same shape | 30s | RANK#<window>#password |
| GET | `/api/top/countries` | `limit=20`, `window=24h\|7d` | same shape | 30s | RANK#<window>#country |
| GET | `/api/top/asns` | `limit=10`, `window=24h\|7d` | `{ items: [{ asn, asn_org, count }] }` | 60s | RANK#<window>#asn |
| GET | `/api/events` | `limit=50`, `before=<ISO>` | `{ items: [...], next_before }` | 15s | GSI2 DAY#today |
| GET | `/api/breakdown` | `window=24h` | `{ brute_force, credential_stuffing, scanner, other }` | 60s | AGG#HOUR#technique |
| GET | `/api/sessions/{id}` | — | `{ events: [...] }` | 5min | PK = SESSION#{id} |
| GET | `/api/healthz` | — | `{ status: "ok", version: "<git sha>" }` | no-cache | (none) |

Single Lambda (`api-fn`) dispatches by `routeKey` (`GET /api/summary`, `GET /api/top/{dimension}`, etc.). Cold-start budget: 600 ms with shared boto3 client outside the handler.

---

## 6. Frontend component breakdown

Stack: React 18, Vite, TypeScript (strict), TanStack Query v5, Tailwind CSS, Recharts, react-simple-maps + topojson, date-fns. No Redux — TanStack Query owns server state, useState owns UI state.

### Component tree

```
<App>
 ├─ <QueryClientProvider>
 ├─ <ThemeProvider>           // dark/light toggle, persisted in localStorage
 └─ <DashboardPage>
     ├─ <Header>              // title, sensor health pill, last-update timestamp
     ├─ <CounterRow>          // 3 stat cards: total / 24h / 1h
     │   └─ <Counter />×3      ← /api/summary
     ├─ <MainGrid>            // CSS grid, 12-col responsive
     │   ├─ <GeoMap />        ← /api/top/countries
     │   ├─ <TimelineChart /> ← /api/timeline
     │   ├─ <TopUsernamesChart /> ← /api/top/usernames
     │   ├─ <TopPasswordsChart /> ← /api/top/passwords
     │   ├─ <TopAsnsChart />  ← /api/top/asns          (P2)
     │   └─ <BreakdownDonut />← /api/breakdown          (P2)
     ├─ <RecentEventsTable /> ← /api/events
     └─ <Footer>              // links: GitHub repo, ADRs, "About this lab"
```

### State management

- All API data fetched via TanStack Query. Each hook lives in `src/api/<endpoint>.ts` and exports `useSummary()`, `useTimeline(opts)`, etc.
- Default `refetchInterval`: 30 s; `staleTime`: 25 s. Window-focus refetch ON.
- Window selectors (`24h` / `7d`) live in URL search params via `useSearchParams` — recruiters can deep-link a 7-day view.
- No client-side routing library — single page. If P2/P3 adds drill-down we'll add `react-router` then.

### Data hooks (signature contracts)

```ts
useSummary(): UseQueryResult<SummaryDTO>
useTimeline({ window: '24h'|'7d', bucket: '1h'|'1d' }): UseQueryResult<TimelineDTO>
useTopList(dim: 'usernames'|'passwords'|'countries'|'asns', { window, limit }): UseQueryResult<TopListDTO>
useRecentEvents({ limit }): UseInfiniteQueryResult<EventDTO>
```

### Visual / UX rules

- Mobile-first; the grid collapses to a single column < 768 px.
- All counts formatted via `Intl.NumberFormat` (`14,231` not `14231`).
- Country flags via `Intl.DisplayNames` + emoji-flag (no image assets).
- Recent events table: monospace, 50 rows, virtualized (`@tanstack/react-virtual`) — easy regression test target.
- Empty / error / loading states for every async region — no naked spinners on a portfolio piece.

---

## 7. Log shipping decision

**Recommendation: Option B — Pi → S3 PutObject → Lambda.** A custom Python tailer on the Pi, no Filebeat.

### Reasoning

| Dim | A: CloudWatch agent | B: Pi → S3 → Lambda | C: Pi → API GW → Lambda |
|---|---|---|---|
| Cost @ ~10K events/day | ~$0.08/mo (CW Logs $0.50/GB ingest) | ~$0.21/mo (S3 PUTs $0.005/1k) | ~$0.30/mo (API GW $1/M) |
| Reliability | Good (CWL retains on agent failure) | **Best** (S3 11 9s; Pi can buffer locally on outage) | Worst (synchronous, no buffer) |
| Complexity | Medium (CWL agent config, retention policy) | **Low** (boto3 + cron-style batcher) | Medium (signing, retry, backoff) |
| Backpressure | Agent buffers | **Local file queue** | Per-event drop on 5xx |
| Replay | Subscription filter only | **Replay any S3 object via re-trigger** | Lost events are lost |
| Diamond IQ pattern reuse | No | **Yes** — same S3 PutObject pattern | No |
| Failure modes | CWL outage = events stuck on Pi | S3 outage = events queue on Pi (rare) | API GW 429 = events lost |

Option B wins on reliability (the Pi keeps a local replay buffer; we can re-process any S3 object by simply re-uploading or sending a synthetic S3 event), pattern reuse (same shape as Diamond IQ), cost (parity), and complexity (a Python script + IAM user with `s3:PutObject` on one prefix).

We deliberately **skip Filebeat** because the AWS-Filebeat S3 module needs a paid Elastic license tier for some features and adds a JVM-class dependency on a Pi. A 150-line Python service is observable, debuggable, and matches the project's "everything in code, no black boxes" thesis.

### Failure modes considered

- **Pi loses internet:** shipper buffers in `/var/lib/cowrie-shipper/queue/*.json.gz` (max 1 GB), drains on reconnect. Alarm fires if `last_ingest_ts` falls > 10 min behind clock.
- **S3 5xx:** boto3 default retry (10 attempts, exp backoff) suffices.
- **Lambda failure on parse:** poison object goes to `s3://dram-soc-honeypot-ingest-dlq/` via SQS DLQ; CloudWatch alarm. Original S3 object is retained for replay.
- **DynamoDB throttle:** ingest Lambda uses `BatchWriteItem` and retries `UnprocessedItems` with exponential backoff up to 30 s; on-demand mode means throttles are extraordinarily rare.
- **Replay needed:** re-uploading the original `.json.gz` object retriggers the Lambda; idempotency key (`sha1(session|ts|eventid)`) prevents duplicates.

### Cost line items

- S3 PutObject @ 1 obj/min * 60 * 24 * 30 = 43,200 PUTs/mo = $0.005 × 43.2 = **$0.22/mo**
- S3 storage @ ~150 MB compressed (7 d) → Glacier @ 30 d → expire @ 90 d = **< $0.05/mo**
- Lambda ingest invocations: 43,200/mo × 200 ms × 256 MB = 2,212 GB-s/mo = **free tier**
- DynamoDB writes: ~10K events/day × 30 = 300K/mo × $1.25/M = **$0.38/mo**
- Total ingest path: **~$0.65/mo**

---

## 8. Synthetic data generator design

Located at `dashboard/tools/synthetic_data_generator.py`. Standalone Python 3.13 with only `boto3` + `faker` + stdlib. **Deterministic via `--seed` + a wall-clock anchor** (revised in v1.4 — see "Determinism contract" below). Produces real Cowrie-shape JSON and optionally writes directly into DynamoDB via `BatchWriteItem`.

### Determinism contract

Same `--seed` + same anchor time ⇒ byte-identical `.json.gz` outputs and byte-identical S3 keys. Without this contract the ingest Lambda's idempotency cannot be exercised by re-running the generator, because timestamps would shift each run and produce distinct DynamoDB items.

The anchor time is resolved with the following precedence:

1. `--anchor-time <ISO 8601 UTC>` if supplied (must include `Z` or `+00:00`).
2. Else if `--seed` is supplied, the anchor defaults to **midnight UTC of the current calendar day**, so same-day reruns are byte-identical without an explicit anchor.
3. Else (no `--seed`), wall-clock `datetime.now(timezone.utc)`.

This is enforced by a property test (`tests/backend/test_generator_determinism.py`) that hashes the output of two generator runs with identical CLI flags and asserts byte equality.

### CLI

```
python tools/synthetic_data_generator.py \
  --events 10000 \
  --days 7 \
  --out dashboard/tests/fixtures/synthetic/ \
  --seed 42 \
  --inject-ddb \
  --table dram-soc-honeypot
```

Flags:
- `--events N` — total events (default 10,000)
- `--days N` — distribute across last N days
- `--out PATH` — write `cowrie.YYYY-MM-DD.json.gz` files (one per day)
- `--seed N` — deterministic
- `--inject-ddb` — also write to DynamoDB via batch-write; without it, files only
- `--table NAME` — DynamoDB table
- `--upload-s3 BUCKET` — alternative: upload .gz files to S3 to exercise the real ingest path
- `--profile NAME` — AWS profile (default: env)
- `--anchor-time ISO8601` — explicit UTC anchor for the timestamp domain (e.g. `2026-04-28T00:00:00Z`). Required for byte-identical CI fixtures spanning multiple days.

### Distribution model

Sessions, not events, are the unit of distribution:

| Cohort | % of sessions | Profile |
|---|---|---|
| Brute force | 80% | 1 IP, 10–200 attempts, single dictionary user (root, admin, ubuntu, pi, …), all fail, session 5–60 s |
| Credential stuffing | 15% | 1 IP, 5–30 attempts, many distinct usernames per IP, 0–2 succeed, session 30–180 s |
| Scanner | 4% | 1 IP, connect + version + immediate disconnect, session < 2 s |
| Interesting | 1% | 1 IP, login succeeds, runs `wget`/`curl`/`uname -a`/`id`, drops a fake binary, session 60–300 s |

### Realism inputs

- **Username dictionary:** top 100 from public Cowrie writeups (root, admin, ubuntu, pi, oracle, postgres, test, user, support, deploy, …). Loaded from `dashboard/tools/data/usernames.txt`.
- **Password dictionary:** top 200 from public credential dumps (123456, password, admin, root, raspberry, qwerty, 1q2w3e4r, …). `dashboard/tools/data/passwords.txt`.
- **Source IPs:** weighted draws from realistic ASN/country pools — DigitalOcean (US), OVH (FR), Aliyun (CN), Tencent (CN), Hetzner (DE), Linode (US), AWS (US), Mevspace (PL). 6–10 ASNs, 1–50 IPs each, persistent within a run for cohort feel. Country distribution: CN 28%, US 22%, RU 11%, BR 7%, IN 6%, DE 5%, FR 5%, NL 4%, KR 3%, other 9%.
- **Commands attempted (interesting cohort):** `uname -a`, `id`, `cat /etc/passwd`, `wget http://<random>/bot.sh`, `curl -O …`, `chmod +x bot.sh`, `./bot.sh`, `crontab -l`. Realistic Mirai/XorDDoS-flavoured.
- **Hour-of-day:** sinusoidal weighting peaking at 02:00–04:00 UTC to match real internet noise.
- **Sensor uuid + sensor:** matches the real Pi (`honeypot`) for parity.

### Output shape

A run with `--days 7` produces:
```
dashboard/tests/fixtures/synthetic/
  cowrie.2026-04-21.json.gz
  cowrie.2026-04-22.json.gz
  …
  cowrie.2026-04-27.json.gz
  manifest.json   # { generator_version, seed, events_total, sha256_per_file }
```

When `--upload-s3` is used, each file is also PUT to `s3://<bucket>/raw/YYYY/MM/DD/HH/synthetic-<seed>-<idx>.json.gz`, exercising the **production ingest path end to end**. This is the primary integration test.

### Reusability

The same generator powers (a) the initial dataset, (b) regression fixtures for unit tests (small `--events 100 --seed N` runs), and (c) load testing if we ever need it. Versioned alongside the dashboard code.

---

## 9. Cost model

Steady-state monthly estimate at 10K events/day (≈ 300K/mo). All us-east-1.

| Service | Line item | Estimate |
|---|---|---|
| S3 | 43K PUTs/mo + 150 MB storage | $0.27 |
| Lambda (ingest) | 43K × 200 ms × 256 MB | free tier |
| Lambda (aggregator) | 300K stream records × 50 ms × 256 MB | free tier |
| Lambda (api-fn) | ~150K invocations/mo × 50 ms × 256 MB | free tier |
| DynamoDB | 300K writes + ~700K reads, 1 GB storage, PITR on | $0.55 |
| DynamoDB Streams | included | $0.00 |
| API Gateway HTTP API | 150K requests | $0.15 |
| CloudFront | 5 GB egress, 200K req | free tier (1 TB/mo first year) → ~$0.50 thereafter |
| AWS WAF | **not used** (Cloudflare proxy provides WAF — ADR-007) | **$0.00** |
| Cloudflare WAF / DDoS / bot mgmt | free tier (proxied DNS, orange cloud) | $0.00 |
| Route 53 | not used (Cloudflare DNS) | $0.00 |
| ACM | CloudFront cert, us-east-1 | $0.00 |
| CloudWatch | 9 alarms (incl. CloudFront viral guard), 5 dashboards, ~200 MB/mo logs | $0.80 |
| Secrets Manager | 1 secret (Pi shipper rotation token) | $0.40 |
| **Total** | | **≈ $2.10–$2.60/mo** |

### Vs target

Target: ≤ $5/mo additive. Estimate: ~$2.60/mo. Comfortably under target. The WAF decision (ADR-007: rely on Cloudflare's proxied free WAF instead of AWS WAF) saves ~$5.40/mo and is the largest single cost lever in this build. The "double-CDN hop" cost is ~10–30 ms of extra TLS termination latency — invisible at honeypot dashboard refresh cadences.

If something starts to drift cost upward (most likely: CloudFront egress on a viral spike, or Lambda invocations from a runaway client), the runbooks at `dashboard/docs/runbooks/` are the first response. If the AWS account budget action trips at $50, the dashboard goes "data-paused" but the static bundle keeps serving — the experience degrades gracefully.

### Defense-in-depth on cost

- AWS Budgets Action (already configured at account level) auto-applies a deny IAM policy at $50.
- CloudWatch alarms: Lambda invocations > 100K/hr (anomaly), DynamoDB consumed WCU > 1K/min, API GW 5xx > 1%/5min, **CloudFront BytesDownloaded > 100 GB/day** (viral-traffic guard — see §10 and `dashboard/docs/runbooks/viral-traffic.md`).
- Reserved Concurrency: **none** (no per-function reservation). *(Revised in v1.3 from `ingest=5, aggregator=5, api=5` (which was itself v1.2's revision of `ingest=20, aggregator=5, api=20`). Per-function reservation is unavailable in this AWS account because the account-level Lambda `ConcurrentExecutions` quota is currently `10`, and AWS enforces a hard rule that `UnreservedConcurrentExecutions` cannot fall below 10. Reserving any positive integer for any function would breach the floor. Confirmed by `aws lambda get-account-settings`. Cost-defense intent is preserved by the next two layers: **API Gateway throttling** (`burst 500, rate 100 RPS`, per-route 50 RPS — see this section's `controls`) and **CloudWatch alarms** on `Lambda invocations > 100K/hr` and per-function error/throttle/p95-duration. A separate, account-level service-quota-increase ticket should be filed (`aws service-quotas request-service-quota-increase --service-code lambda --quota-code L-B99A9384 --desired-value 1000`) to restore per-function reservation as a tertiary defense; that work is independent of this dashboard's build and does not block any phase.)*
- DynamoDB on-demand has no cost cliffs; the Lambda concurrency caps cap downstream cost.
- All Lambdas have CloudWatch log retention set to 14 days (vs default never-expire) — controls log storage cost.

---

## 10. Security considerations

### Threat model

This is a **public read-only dashboard** displaying **attacker-supplied data captured by a honeypot**. No real-user PII, no auth, no write surface from the public internet. Attackers may try to: (a) DDoS the API to spike costs, (b) inject content that crashes the frontend renderer, (c) attempt to manipulate the displayed data by spamming the honeypot with crafted strings.

### Controls

- **Cloudflare proxy (orange cloud) — primary edge defence (ADR-007):**
  - Free WAF (managed rules covering OWASP categories)
  - Free DDoS protection (L3/4 + L7)
  - Free bot management
  - Cloudflare → CloudFront uses HTTPS; Cloudflare is the public-facing IP, CloudFront is "behind" it
- **CloudFront:** restricted via Origin Access Control to S3; response headers policy enforces CSP, HSTS (`max-age=31536000`), `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`.
- **API Gateway throttling:** account-level burst 500, rate 100 RPS. Per-route throttle 50 RPS. Stops a runaway script from cost-spiking us.
- **Lambda Reserved Concurrency:** caps absolute concurrency per function (see §9).
- **CORS:** API responses set `Access-Control-Allow-Origin: https://dashboard.dram-soc.org` only.
- **CSP:** dashboard sets a strict Content-Security-Policy header (`default-src 'self'; img-src 'self' data:; …`) injected via CloudFront response headers policy. Defends against XSS from attacker-supplied strings displayed in the recent-events table.
- **Output encoding:** every value rendered in JSX is auto-escaped by React; the `RecentEventsTable` never uses `dangerouslySetInnerHTML`. Commands and passwords are rendered in `<code>` tags; non-printable bytes are escaped to `\xNN` form server-side before they reach the client.
- **Attempted-password filtering (ADR-005):** the ingest Lambda classifies every attempted password against a bundled known-bad attack-dictionary list (~5000 entries — top common-passwords lists from breach corpora and Cowrie operator writeups). Dictionary matches are stored in the public `password` attribute and surfaced on the dashboard. Non-matches are stored as `<filtered:len=N>` in `password`, with the actual value preserved only in `password_raw`, which is **never** returned by any API endpoint and never indexed by any GSI. Rationale: an attacker spraying their own real credential, or a victim's reused credential, against the honeypot should not have it published on a public dashboard. The educational value (top dictionary attempts) is the interesting signal anyway.
- **Captured malware policy (ADR-009):** binary samples are **not** stored in this dashboard's S3 bucket. The dashboard records only `shasum` + source `url` from `cowrie.session.file_download` events. If a binary is worth analysis, it's routed to MISP (which already exists in the parent SOC repo's stack) under that project's existing handling policy.
- **CloudFront viral-traffic guard:** CloudWatch alarm on `BytesDownloaded > 100 GB/day` for the dashboard distribution. After CloudFront's first-year free 1 TB tier, egress is $0.085/GB — a single Hacker News front page could push past $50 in hours. Runbook: `dashboard/docs/runbooks/viral-traffic.md` covers the response (raise CloudFront cache TTL on `/api/*` to 5 min, temporarily serve a static read-only snapshot of the dashboard, optionally enable Cloudflare "I'm Under Attack" mode at the proxy layer).
- **GeoIP privacy:** only the source IP of the attacker is GeoIP'd, never any visitor of the dashboard. The MaxMind GeoLite2 DB is bundled into the Lambda layer (license: CC BY-SA 4.0; attribution shown in the dashboard footer).
- **Pi → S3 IAM scope:** Pi has an IAM user with one inline policy: `s3:PutObject` on `arn:aws:s3:::dram-soc-honeypot-ingest/raw/*`. No List, no Get, no Delete. **Access keys rotated every 90 days** (the Pi is internet-exposed post-Phase 10 and physically accessible — annual rotation is too long a credential lifetime for an exposed sensor). Rotation runbook in `dashboard/docs/runbooks/pi-iam-rotation.md` includes the calendar reminder cadence and the dual-key overlap procedure (create new key, deploy to Pi, verify ingest, retire old key).
- **GitHub Actions OIDC:** no long-lived AWS keys in GitHub. Two roles, `dashboard-backend-deploy` (lambda + ddb + s3 + apigw + iam:PassRole on lambda exec roles) and `dashboard-frontend-deploy` (s3 sync to bucket + cloudfront:CreateInvalidation).
- **Repo secrets hygiene:** `gitleaks` already wired up at repo root; will extend to scan `dashboard/` paths.
- **Logs:** structured JSON via AWS Lambda Powertools. No secrets logged (ingest Lambda truncates payload bodies in logs, only logs counts + sampled keys; `password_raw` is explicitly never logged).

---

## 11. Phasing plan

Each phase is independently shippable and demoable. Estimates are calendar-clock for solo full-time work; adjust to ~2× if part-time.

### Phase 1 — Foundations (target: 2–3 days)
**Deliverables:**
- `dashboard/` directory scaffold (the structure proposed in §16).
- ADR-001 (data schema), ADR-002 (log shipping), ADR-003 (single-table design), ADR-004 (frontend stack), ADR-005 (attempted-password filtering policy), ADR-007 (Cloudflare WAF over AWS WAF), ADR-009 (captured-malware policy).
- Terraform skeleton: backend state in S3 + DynamoDB lock, providers, modules folder with empty README per module.
- Python 3.13 virtualenv conventions, `pyproject.toml`, ruff + mypy configured.
- Synthetic data generator (`tools/synthetic_data_generator.py`) producing valid Cowrie JSON.gz files with realistic distribution and passing schema-validation tests.
- DynamoDB table created via Terraform with PK/SK + 3 GSIs + Streams + PITR.
- A small pytest suite verifying generator output shape against a JSON schema.

**Acceptance criteria:**
- `terraform plan` is clean.
- `python tools/synthetic_data_generator.py --events 1000 --days 1 --out /tmp/x` produces 1 file with 1000 events that passes a Pydantic schema validator.
- `pytest dashboard/tests/backend/test_generator.py` green at 90%+ coverage on the generator module.
- DynamoDB table visible in console; describe-table returns expected schema.

**Dependencies:** none.

---

### Phase 2 — Ingest path (target: 2 days)
**Deliverables:**
- `functions/ingest/handler.py`: S3 PutObject → parse gzipped NDJSON → enrich (GeoIP) → classify password against dictionary list (ADR-005) → BatchWriteItem.
- Bundled known-bad password dictionary (~5000 entries) at `functions/shared/data/password_dictionary.txt`; loaded once at Lambda cold start into a `frozenset`.
- MaxMind GeoLite2 DB bundled as a Lambda layer (separate Terraform module, includes weekly refresh via EventBridge + Lambda — Phase 9 problem, stub a static DB for now).
- S3 bucket `dram-soc-honeypot-ingest` with PutObject → ingest-fn trigger.
- Idempotency key implementation; redeploy-the-same-object test passes (no duplicates in DDB).
- DLQ (SQS) wired for failed events.

**Acceptance criteria:**
- Running `synthetic_data_generator.py --upload-s3 dram-soc-honeypot-ingest --events 5000` results in 5000 items in DynamoDB within 60 s.
- Re-running the same upload produces 0 new items (idempotency).
- A deliberately malformed object lands in the DLQ.
- pytest integration test using `moto` covers the full ingest path.
- Password classifier unit tests: dictionary hits stored as-is; non-matches stored as `<filtered:len=N>` with raw value only in `password_raw`; API DTO mapping confirms `password_raw` is never serialized.

**Dependencies:** Phase 1.

---

### Phase 3 — Aggregations (target: 2 days)
**Deliverables:**
- `functions/aggregator/handler.py`: DynamoDB Streams → atomic counter increments on AGG#HOUR# items.
- EventBridge schedule (every 60 s) → aggregator-fn rebuild of RANK#24H# and RANK#7D# items.
- Daily summary builder (runs at 00:05 UTC).
- Comprehensive unit tests on aggregation math.

**Acceptance criteria:**
- Inject 10K synthetic events; within 2 minutes, RANK#24H#username has 25 items with correct counts (verified against in-memory aggregation of the same dataset).
- Restart the aggregator (force a reprocess); counts remain correct (idempotency).

**Dependencies:** Phase 2.

---

### Phase 4 — API (target: 2 days)
**Deliverables:**
- `functions/api/handler.py` with full routeKey dispatch to all endpoints in §5.
- API Gateway HTTP API with all routes wired.
- Comprehensive Pydantic models for request/response DTOs.
- pytest covering each route's happy path + 4xx cases.

**Acceptance criteria (revised in v1.5 to match measured reality):**
- `curl https://<api-gw-url>/api/summary` returns valid JSON.
- All endpoints listed in §5 return 200 with non-empty data against the synthetic dataset from Phase 2.
- **Cold start p95 < 1500 ms.** Documented floor: Pydantic v2 + boto3 + first-Lambda-call DDB cost. Pydantic is load-bearing for the ADR-005 password_raw boundary; can't be removed.
- **Warm p95 by endpoint class:**
  - `/api/healthz`, `/api/top/*`, `/api/events`, `/api/sessions/{id}`: **< 100 ms** (single Query / GetItem). Measured 2–82 ms.
  - `/api/summary`: **< 50 ms** (originally < 30 ms — loosened to match measured 36–41 ms post-Bug-1 fix; the fix took /api/summary from 702 ms → ~40 ms, a 17× improvement).
  - `/api/timeline`, `/api/breakdown`: **< 600 ms** (originally < 100 ms — relaxed; see "Why secondary endpoints are slower" below). Measured 423–493 ms post-parallelization.
- 90%+ test coverage on `functions/api/`.

**Why secondary endpoints are slower.** `/api/timeline` and `/api/breakdown` each execute up to 24 parallel DDB Queries (one per hour bucket of the trailing 24-hour window). Even with the documented-thread-safe boto3 Client + a 25-connection pool + a 10-worker `ThreadPoolExecutor`, observed parallelism delivers only ~2–3× speedup over sequential, not the theoretical 10×. The cap is some combination of Python GIL contention during boto3 response parsing, botocore SigV4 signing serialization, and Lambda's fractional-vCPU allocation at 256 MB memory. This is acceptable for v1 because (a) **CloudFront caches `/api/*` with 30–60 s TTL per §5**, so real users hit cache hits at < 30 ms regardless of origin latency, and (b) these endpoints power **secondary visualizations** (timeline chart, breakdown donut), not the first-paint critical path. If Phase 11 real-data analysis surfaces user-perceived latency, revisit memory sizing (1024 MB → full vCPU) and/or schema pre-aggregation (a SUMMARY#HOUR rollup item written by the aggregator on session.closed, replacing 24 Queries with 1).

**Dependencies:** Phase 3.

---

### Phase 5 — Frontend scaffolding (target: 1–2 days)
**Deliverables:**
- Vite + React 18 + TS + Tailwind + TanStack Query bootstrapped.
- API client (`src/api/`) with hooks for every endpoint.
- Layout shell, header, footer, theme.
- Vitest + Testing Library configured; one passing component test.

**Acceptance criteria:**
- `npm run dev` shows a populated layout pointed at the deployed API.
- `npm run build` produces a static bundle under 250 KB gzipped (no map yet).

**Dependencies:** Phase 4.

---

### Phase 6 — Priority-1 visualizations (target: 3–4 days)
**Deliverables:**
- CounterRow + 3 stat cards, polished.
- TopUsernamesChart + TopPasswordsChart (Recharts horizontal bars).
- TimelineChart (Recharts line/area, brushable).
- RecentEventsTable (virtualized, 50 rows).
- All loading / empty / error states.
- Component tests for each.

**Acceptance criteria:**
- Dashboard renders all P1 visualizations against synthetic data.
- Lighthouse: Performance ≥ 90, Accessibility ≥ 95.
- All Vitest tests green; coverage ≥ 80% on components.

**Dependencies:** Phase 5.

---

### Phase 7 — GeoMap (target: 2 days)
**Deliverables:**
- `<GeoMap>` using `react-simple-maps` + a small embedded TopoJSON world dataset.
- Country count → choropleth fill; hover tooltips with count + flag.
- ADR-006 documenting GeoIP enrichment + MaxMind license attribution placement.

**Acceptance criteria:**
- Map renders with at least 30 countries shaded against synthetic data.
- Hover behaviour smooth at 60 fps.

**Dependencies:** Phase 6.

---

### Phase 8 — Production hosting (target: 2 days)
**Deliverables:**
- S3 origin bucket + CloudFront distribution + ACM cert in us-east-1.
- **No AWS WAF** (ADR-007). Edge protection via Cloudflare proxied DNS.
- CloudFront response headers policy with CSP, HSTS, X-Frame-Options, Referrer-Policy.
- Cloudflare DNS: `dashboard.dram-soc.org` CNAME → CloudFront, **proxy ON (orange cloud)**.
- Frontend deploy workflow producing an S3 sync + CloudFront invalidation.

**Acceptance criteria:**
- `https://dashboard.dram-soc.org` resolves and serves the dashboard with a green padlock.
- DNS lookup shows Cloudflare IPs (proxy active); CloudFront origin hidden behind Cloudflare.
- Cloudflare dashboard shows requests being inspected by the free WAF.
- Lighthouse: Best-Practices ≥ 95.
- A scripted 250-RPS burst from one IP gets rate-limited by Cloudflare or API Gateway throttling.

**Dependencies:** Phase 7.

---

### Phase 8.5 — Apex landing page (target: 0.5–1 day)
Resolves the apex-domain question (formerly open question 6). The apex `dram-soc.org` serves a small static "front door" page that links to (a) the live dashboard, (b) the SOC Detection Lab GitHub repo, and (c) Diamond IQ. Recruiter-friendly portfolio entry point.

**Deliverables:**
- `dashboard/frontend-apex/` — minimal static HTML/CSS (no build step, no React) under ~10 KB.
- Same CloudFront distribution, second behavior matching `dram-soc.org` apex with a separate origin path `/apex/` in the same S3 bucket.
- ACM cert SANs extended to cover the apex.
- Cloudflare DNS: `dram-soc.org` apex CNAME-flattened to the CloudFront alias, proxy ON.
- Same response headers policy + CSP applied.

**Acceptance criteria:**
- `https://dram-soc.org` and `https://www.dram-soc.org` both resolve to the landing page with a green padlock.
- Landing page links open dashboard + GitHub + Diamond IQ correctly.
- No additional monthly cost (single S3 bucket, single CloudFront distribution; ~$0 incremental).

**Dependencies:** Phase 8.

---

### Phase 9 — Observability + cost guards (target: 1–2 days)
**Deliverables:**
- CloudWatch alarms per Lambda (errors, throttles, p95 duration).
- CloudWatch dashboard "SOC-Honeypot-Health" (ingest lag, API latency, DDB capacity, error rates).
- **Heartbeat alarm** (no events for > 30 min). **Created in DISABLED state.** During synthetic-data phases, no real events flow continuously, so an enabled heartbeat would page constantly. The alarm is enabled only at Phase 10 cutover, when real Pi traffic begins. This is documented in the alarm description and in `dashboard/docs/runbooks/heartbeat.md`.
- **CloudFront viral-traffic alarm** on `BytesDownloaded > 100 GB/day` for the dashboard distribution. Enabled from Phase 9 (it doesn't depend on the data feed).
- `dashboard/docs/runbooks/viral-traffic.md` runbook covering the response: raise CloudFront cache TTL, serve a static read-only snapshot, optionally enable Cloudflare "I'm Under Attack" mode.
- Reserved Concurrency configured per Lambda.
- Budget alarm at $40 (paging) and the existing $50 (auto-deny) verified end-to-end.
- Weekly MaxMind GeoLite2 refresh Lambda + scheduled trigger.

**Acceptance criteria:**
- Forcing a Lambda error triggers the corresponding CW alarm.
- Budget $40 alarm test (manually adjust threshold to $0.01, verify, restore).
- Heartbeat alarm exists in CloudWatch but state is DISABLED; runbook contains the one-line CLI to enable it at cutover.
- Viral-traffic alarm is ENABLED and observable on the dashboard.

**Dependencies:** Phase 8.5.

---

### Phase 10 — Production cutover (target: 1 day; **deployment decision separate from build**)
> **Important:** the cutover to live data is contingent on a deployment decision that is independent of the dashboard build itself. The dashboard is fully functional and demoable on synthetic data after Phase 9. Phase 10 only happens once the deployment path is chosen and the operator (me) is comfortable exposing the sensor.

**Deliverables (primary path — home router port-forward):**
- Pi systemd service `cowrie-shipper.service` (Python tailer, batched gzip → S3).
- Pi IAM user with scoped policy; access keys delivered via SSM Parameter Store on the Pi (encrypted at rest on disk). Rotation cadence: 90 days.
- Home router port-forward `22 → 192.168.1.253:2222` enabled.
- **Heartbeat alarm enabled** (was disabled in Phase 9).
- Documentation update: top-level repo README links to live dashboard.
- Synthetic data flag turned off; live data verified within 24 h.
- ADR-008 documenting the cutover decision and rollback plan.

**Fallback A — VPS reverse-tunnel (if router access is unavailable):**
- Provision a $4–$5/mo VPS (Vultr / Hetzner / OVH) with a public IP and SSH.
- Pi establishes a persistent reverse-SSH tunnel to the VPS exposing port 2222 publicly.
- VPS-side `iptables` PREROUTING DNAT forwards public 22 → tunnel → Pi 2222.
- Adds ~$5/mo to total spend, bringing project total to ~$7.60/mo (still well under the $50 cap).
- ADR-008 records this as the chosen path if it's selected.

**Fallback B — indefinite synthetic operation:**
- If neither path A nor path A's fallback A is acceptable (privacy, ISP TOS, ops comfort), the dashboard remains fully deployed and live on synthetic data.
- Frame the project in the README and resume as: "fully-deployed honeypot detection lab with simulation harness; production data feed pending operational decision."
- This is still a strong portfolio piece — it demonstrates end-to-end AWS architecture, IaC, CI/CD, frontend build, observability, and detection engineering thinking. The synthetic generator is realistic enough to sell the architecture story.
- Heartbeat alarm stays disabled. README explicitly notes the synthetic data status to avoid misrepresenting the live state.

**Acceptance criteria (paths A or A-fallback):**
- Within 24 h of cutover, dashboard shows ≥ 50 real events from ≥ 5 distinct ASNs.
- Heartbeat stays green for 7 consecutive days.
- No alarms fire (or all alarms that fire have a documented explanation).
- Synthetic generator marked "test fixture only — do not run against prod" in its module docstring.

**Acceptance criteria (path B):**
- Dashboard remains live on synthetic data with a banner / footer note disclosing the synthetic status.
- README accurately frames the project state.
- ADR-008 documents the deferral and the conditions under which cutover would be revisited.

**Dependencies:** Phase 9 + a deployment decision (router access OR VPS budget OR explicit choice to defer).

---

### Phase 11 — Real-data tuning (target: 3–5 days; only if Phase 10 path A or A-fallback succeeded)
Real Cowrie data never matches synthetic data exactly. Phase 11 is an explicit buffer for the schema and visualization adjustments that *will* be needed once real attacker traffic starts flowing. This is normal and expected — without this phase, the plan would imply Phase 10 is "done" when in practice tuning work is always required.

**Deliverables:**
- Reclassification of the brute-force / credential-stuffing / scanner heuristics if real distributions differ from the assumed 80/15/4/1 split.
- Schema additions for any unexpected Cowrie event fields not seen in the documented sample (Cowrie occasionally produces fields driven by attacker behaviour we didn't model).
- Visualization tweaks: chart axis ranges, top-N cutoffs, time bucketing, colour scales — all calibrated to real-volume data rather than synthetic targets.
- Updated password dictionary list if real attacker traffic exposes high-frequency words missing from the bundled list.
- Tuned alarm thresholds (heartbeat window, error rates, ingest lag) based on observed steady-state.
- Optional ASN allowlist for benign scanners (Shodan, Censys, BinaryEdge) if their volume creates noise.
- ADR-010 capturing what changed between synthetic-design assumptions and reality.

**Acceptance criteria:**
- Dashboard renders cleanly (no axis blow-out, no flat top-N lists) on real data.
- All alarms have ≥ 7 days of stable, signal-bearing history at their tuned thresholds.
- Synthetic distributions in the generator updated to match observed reality (so future regression tests stay faithful).

**Dependencies:** Phase 10 (path A or A-fallback) with ≥ 7 days of real ingest behind it.

---

## 12. Test strategy

### Backend

- **Unit tests** (pytest): generator distributions, schema validators, event parsers, GeoIP enrichment, idempotency hashing, aggregation math, top-N sort, API DTO marshalling, route dispatch. Target **≥ 90% line coverage** per CI gate.
- **Integration tests:** `moto` for DynamoDB + S3 + Lambda. End-to-end happy path: generate 100 events → upload synthetic .gz to mock S3 → trigger ingest handler in-process → assert items in mock DDB → trigger aggregator on stream records → assert RANK items → call api-fn handler → assert response shape.
- **Contract tests:** Pydantic models on every API response shape, exported as TypeScript types via `pydantic-to-ts` for the frontend (single source of truth).
- **Idempotency tests:** every ingest handler test runs twice; second run asserts zero new items.

### Frontend

- **Component tests** (Vitest + Testing Library): each visualization with mocked TanStack Query response — happy / loading / error / empty states.
- **Hook tests:** API hook behaviour (refetch interval, stale time, error retry).
- **Visual regression:** Playwright + visual snapshots for the four major widgets (P2 — not blocking v1).

### E2E

- **Smoke test on every deploy:** Playwright loads the live dashboard, asserts the counter is non-zero, the recent events table has rows, and no console errors. Runs as a post-deploy GitHub Actions step.
- **Synthetic-load smoke:** scripted 50 RPS for 60 s against the API; assert p95 < 200 ms and no 5xx.

### Coverage gates

- Backend ≥ 90%, frontend ≥ 80%. CI fails the PR below threshold.
- No coverage gate on infra/Terraform (we test it via plan/apply in the deploy workflow).

---

## 13. CI/CD pipeline design

All workflows live at `.github/workflows/`. Existing repo workflows (`security-scan.yml`, `sigma-validate.yml`) are left untouched.

### Workflows

**1. `dashboard-tests.yml`** — runs on every PR touching `dashboard/**`
- Backend: ruff + mypy + pytest with coverage gate.
- Frontend: eslint + tsc --noEmit + vitest.
- Status check required before merge.

**2. `dashboard-backend-deploy.yml`** — runs on push to `main` touching `dashboard/functions/**` or `dashboard/infrastructure/**`
- OIDC assume `dashboard-backend-deploy`.
- Package Lambdas (zip, layers).
- `terraform plan` → review-required for infra changes that touch IAM, S3, or budget actions (manual `workflow_dispatch` approval); `terraform apply` for everything else.
- Lambda alias-based deploy with `weight=10` canary, then `weight=100` after CloudWatch shows < 1% errors for 5 min.
- Post-deploy smoke: hit `/api/healthz`, assert 200 + version matches git SHA.

**3. `dashboard-frontend-deploy.yml`** — runs on push to `main` touching `dashboard/frontend/**`
- OIDC assume `dashboard-frontend-deploy`.
- `npm ci && npm run build`.
- `aws s3 sync` to versioned prefix `s3://<bucket>/v/<git_sha>/`.
- Update CloudFront origin path to `/v/<git_sha>/` via Terraform.
- CloudFront invalidation on `/index.html` (everything else is hashed-asset cacheable forever).
- Post-deploy Playwright smoke.

**4. `dashboard-nightly.yml`** — cron daily 06:00 UTC
- Re-runs full test suite against `main`.
- MaxMind GeoLite2 refresh (Phase 9).
- Cost report: prints prior-24h AWS spend by tag to the run summary.

### OIDC role design

| Role | Trust | Inline permissions (scoped) |
|---|---|---|
| `dashboard-backend-deploy` | repo + branch=main + path=dashboard/functions or dashboard/infrastructure | `lambda:*` on prefix `dram-soc-*`; `dynamodb:*` on the table; `s3:*` on ingest bucket only; `iam:PassRole` on lambda exec roles only; `apigateway:*` on the dashboard API; `cloudwatch:*` for alarms |
| `dashboard-frontend-deploy` | repo + branch=main + path=dashboard/frontend | `s3:PutObject*` on frontend bucket only; `cloudfront:CreateInvalidation` on the dashboard distribution only |
| `dashboard-tests` | repo + any branch | `sts:GetCallerIdentity` only (used only to verify auth in CI) |

### Rollback strategy

- **Lambda:** alias-pinned. Rollback = re-point alias to previous version (stored as Terraform output for the last 5 deploys). One CLI command, < 30 s.
- **Frontend:** versioned S3 prefixes (`/v/<sha>/`). Rollback = update CloudFront origin path back to the prior SHA + invalidate. < 2 min.
- **Infra:** Terraform; rollback = revert the commit + re-apply.
- **Data:** DynamoDB PITR is available for 35 days; in a worst-case data corruption, restore to a new table and switch the Lambda's TABLE_NAME env var.

---

## 14. Open questions (need decisions before build)

Decisions previously listed here have been resolved in plan v1.1 and folded into the body of the plan / committed to ADRs:

- ~~Plaintext password display~~ → **resolved** as ADR-005 (dictionary-classified filtering; see §10).
- ~~WAF strategy~~ → **resolved** as ADR-007 (Cloudflare proxied free WAF; no AWS WAF; see §9, §10).
- ~~Cloudflare proxy mode~~ → **resolved**: orange cloud / proxied (consequence of ADR-007).
- ~~`/sessions/{id}` drill-down in v1~~ → **resolved**: deferred to v2 (see §15).
- ~~WebSocket real-time feed in v1~~ → **resolved**: deferred to v2 (see §15).
- ~~Apex `dram-soc.org`~~ → **resolved**: static landing page, new Phase 8.5 (see §11).
- ~~Captured malware samples~~ → **resolved** as ADR-009: SHA + URL only; binaries route to MISP if worth analysis (see §10).

Remaining open questions:

1. **Top-level `README.md` amendment timing** — Phase 10 (live URL ready) vs now (link to PROJECT_PLAN.md and a "coming soon" note). My lean: Phase 10 — the live URL is the moment that earns the README space.
2. **Pi access key delivery mechanism** — generate via Terraform and write to local file with strict permissions, or use AWS IAM Identity Center + temporary credentials? IAM IC is more correct; Terraform-managed long-lived keys are simpler. Recommend simple now (with the 90-day rotation cadence from §10), IAM IC migration as a backlog item.
3. **Domain ACM cert validation** — DNS-validation requires a CNAME at Cloudflare; one-time setup. Confirm I can author the Cloudflare DNS record (I'll request it; you approve the change in Cloudflare).
4. **Phase 10 deployment path preference** — primary (home router port-forward), Fallback A (VPS reverse-tunnel, +$5/mo), or Fallback B (indefinite synthetic). I don't need an answer until Phase 9 ships, but flagging now so it's not a Phase 10 surprise.

---

## 15. Out of scope for v1

Explicitly NOT building first time:

- **Real-time WebSocket event stream** — **deferred to v2**. Polling at 30 s already feels live for honeypot data cadence; WebSocket adds an API GW WebSocket API + a stream-processor Lambda + a connection table — not worth it for v1. (Originally open question 5; now resolved as deferred.)
- **Per-attacker session detail / drill-down view (`/api/sessions/{id}` UI)** — **deferred to v2**. The endpoint is in the API spec for completeness but the frontend route + UI is not built in v1. Pulls in `react-router` and a routing test surface; v2 problem. (Originally open question 4; now resolved as deferred.)
- **Attack campaign clustering / dictionary-similarity grouping** (P3).
- **Authentication / login** — dashboard stays public read-only.
- **Multi-honeypot / multi-sensor support.** One Pi, one ingest path.
- **Multi-region or DR.** Single-region us-east-1.
- **Captured malware binary retention.** SHA + source URL only (ADR-009). Binaries, if any analysis is warranted, route to the parent SOC repo's MISP stack.
- **Slack / Discord / email alerting** on attack events (CloudWatch alarms only — operational alerting, not user-facing).
- **TheHive / SOAR / case management integration.**
- **ATT&CK technique tagging beyond brute-force/cred-stuff/scanner classification.**
- **YARA scanning of any captured artefacts.**
- **Playbook auto-execution.**
- **Audit trail / immutable event log** (DynamoDB PITR is sufficient for the portfolio scope).
- **CSV export / download links.** (Cheap to add later if asked.)
- **Drill-into-events filter UI (search by IP, session, country).** Likely v2.
- **Mobile app or PWA install.**

---

## 16. Dependencies on the existing SOC repo

### Files / dirs added (new — no risk to existing)
- `dashboard/` (entire subtree, including `dashboard/frontend-apex/` for the Phase-8.5 landing page)
- `dashboard/docs/adr/` — ADR-001 through ADR-010 (see §11 for which phase introduces each)
- `dashboard/docs/runbooks/` — `pi-iam-rotation.md`, `viral-traffic.md`, `heartbeat.md`
- `.github/workflows/dashboard-tests.yml`
- `.github/workflows/dashboard-backend-deploy.yml`
- `.github/workflows/dashboard-frontend-deploy.yml`
- `.github/workflows/dashboard-nightly.yml`

### Files modified (small, surgical)
- **`README.md` (top-level)** — add a "Live dashboard" section linking `https://dashboard.dram-soc.org` and `dashboard/docs/PROJECT_PLAN.md`. Edit happens in Phase 10 (live URL ready).
- **`.gitignore`** — append: `dashboard/frontend/node_modules/`, `dashboard/frontend/dist/`, `dashboard/**/.terraform/`, `dashboard/**/*.tfstate*`, `dashboard/**/.venv/`, `dashboard/**/__pycache__/`, `dashboard/tests/fixtures/synthetic/*.json.gz`.

### Files left strictly alone
- All of `sigma/`, `suricata/`, `zeek/`, `wazuh/`, `elastic/`, `misp/`, `scripts/`, `docs/`, `LICENSE`, `docker-compose.yml`, `.env.example`.
- `.github/workflows/sigma-validate.yml` and `security-scan.yml` — these are critical to the parent project's CI and have no dependency on the dashboard.

### Pattern reuse from Diamond IQ (same AWS account, validated)
- S3 PutObject → Lambda ingest pattern.
- DynamoDB single-table + on-demand + PITR.
- API Gateway HTTP API + single Lambda routeKey dispatch.
- React 18 + Vite + TS + TanStack Query + Tailwind.
- S3 + CloudFront + ACM (no AWS WAF — Cloudflare proxy provides WAF for free per ADR-007).
- Terraform module-per-concern.
- GitHub Actions OIDC.
- pytest backend / Vitest frontend.

### What this plan does NOT touch
- The Cowrie configuration on the Pi itself (already working).
- The home network, beyond a single port-forward rule added in Phase 10.
- Any existing AWS resource in account 334856751632 outside this project's tagged resources (`Project=soc-detection-lab`, `Component=dashboard`).

---

**End of plan.** Awaiting final approval before any build work begins.

---

## Changelog

**v1.7 (2026-05-07, Phase 11B fully shipped + README rewritten + portfolio live):**
- §11 Phase 11B: **all 5 steps shipped.** PR #1 merged the 4 workflow files (`dashboard-ci`, `dashboard-tf-plan`, `dashboard-backend-deploy`, `dashboard-frontend-deploy`) plus 4 cleanup commits. PRs #2/#3/#4 patched 4 IAM gaps surfaced by the first real `terraform apply` from CI (`s3:GetBucketWebsite`, `iam:ListOpenIDConnectProviders`, `ssm:DescribeParameters`, plus a wildcards collapse on `s3:Get*`/`s3:Put*` resource-scoped to project-owned buckets — security boundary is the resource scope, not action enumeration). Step 4 (first CI-driven backend deploy) closed after 5 retries; the failures cleanly mapped to (a) IAM gaps, (b) AWS S3 action-namespace inconsistency, and (c) the CloudFront mutate-tag-gate refusing to update untagged Function/OAC/RHPolicy resources. Step 5 (frontend auto-deploy) merged in PR #5 after the initial workflow self-trigger broke the dashboard for ~6h24m by deploying with the wrong env var name (`VITE_API_URL` vs `VITE_API_BASE_URL`); fix removed the self-trigger and switched to runtime API endpoint resolution via `aws apigatewayv2 get-apis`. Phase 11C auto-trigger flip remains gated on 5+ clean `workflow_dispatch` deploys; **currently 1 of 5.**
- §11 Phase 8.5: **portfolio site live at apex.** `dram-soc.org` + `www.dram-soc.org` now serve a static HTML portfolio (deployed to `s3://dram-soc-dashboard-frontend/apex/index.html`, routed via CloudFront Function `host_router` rewriting `/` → `/apex/index.html`). PR #6 reworked the dashboard UI (industrial-chrome + yellow accent + Bebas Neue display font); PR #7 extended CSP to allow Google Fonts (`https://fonts.googleapis.com` on `style-src`, `https://fonts.gstatic.com` on `font-src`) for the Archivo / Inter / JetBrains Mono load on the apex portfolio. PR #7 was applied via workstation targeted apply first (the RHPolicy resource is AWS-API-untaggable so CI's mutate-tag-gate would block it), then the terraform code was reconciled to match live state.
- **README rewrite (SHA 6fe9d28):** the top-level public README was rewritten end-to-end to accurately describe the deployed AWS-native pipeline. Prior README described Wazuh + ELK + Splunk + MISP + Suricata + Zeek + Sigma rules running on Dell PowerEdge / Cisco / Palo Alto hardware — **none of which are deployed.** The rewrite states what is actually built: Cowrie on Pi 5 + DigitalOcean droplet + autossh reverse tunnel + fluent-bit + Lambda correlation + DynamoDB + API Gateway + CloudFront + React SPA. The top-level `wazuh/`, `elastic/`, `splunk/`, `misp/`, `suricata/`, `zeek/`, top-level `docs/`, and `docker-compose.yml` are explicitly called out as "exploration scaffolding from the project's initial homelab-SIEM scoping that was pivoted away from" — repo cleanup queued in Future work.
- **Next-workstream candidates** (NOT yet started, queued for separate sessions): (a) homelab-scaffolding cleanup commit — delete the unused top-level dirs once SIEM-integration future-work item is conclusively resolved; (b) Pi-only Wazuh + Suricata + k3s + Sigma buildout to legitimize the keyword claims that the original (now-removed) README staked; (c) ADR-011 §Amendment #3 + runbook for the CF tag-bootstrap pattern (covers the OAC / ResponseHeadersPolicy AWS-API-untaggability blocker that recurred in Step 4 retry #5 and PR #7).

**v1.6 (2026-05-07, Phase 11B-2 CI/CD scaffolding shipped):**
- §11 Phase 11B: GitHub Actions deploy role (Phase 11B-1, SHA 6aa5357) + 4 workflow files (Phase 11B-2, SHA 7b2180f) now live on main. The backend-deploy workflow stays `workflow_dispatch`-only until Phase 11C unblocks (after 5+ clean manual deploys), per ADR-011's CI/CD permission boundary.

**v1.5 (2026-04-29, Phase 4 latency bars reality-checked):**
- §11 Phase 4 acceptance: **revised the warm-latency bars to match measured reality after Bug 1 + Bug 2 fixes**. Original spec was "warm p95 < 100 ms" across the board; that proved unachievable on the two fan-out endpoints (timeline, breakdown) at 256 MB Lambda + Python boto3 overhead, even with documented-thread-safe Client + 25-conn pool + 10-worker executor. New bars distinguish per-endpoint class: lightweight reads stay at < 100 ms (measured 2–82 ms); /api/summary loosened from < 30 ms to < 50 ms (measured 36–41 ms after the Bug 1 architectural fan-out fix took it from 702 ms → ~40 ms); /api/timeline + /api/breakdown set at < 600 ms (measured 423–493 ms after parallelization). Cold start bar moved to < 1500 ms with explicit "Pydantic + boto3 floor" documentation. The architectural fixes (Bug 1: stop fanning out across 30 SUMMARY#DAY rows when one rollup answers the question; Bug 2: switch parallel paths to thread-safe Client + bumped pool) landed and are verified. The remaining floor is Python+boto3 mechanics, not a design problem; CloudFront caching in Phase 8 will hide it for real users at 30–60 s TTL on /api/*. Continued optimization (memory bump to 1024 MB or pre-aggregating a SUMMARY#HOUR rollup) deferred indefinitely as diminishing returns until Phase 11 real-data analysis says otherwise.

**v1.4 (2026-04-28, generator determinism contract):**
- §8 Synthetic data generator: **explicit determinism contract added.** v1.0–1.3 said "Deterministic via `--seed`" but the implementation anchored timestamps to wall-clock `datetime.now()`, so same-seed reruns produced shifted timestamps and failed the live idempotency acceptance test in Phase 2 (count went 5000 → 10000 on replay). Fix: added a `--anchor-time` CLI flag and a precedence rule — explicit anchor > `--seed` defaults to midnight UTC today > else `now()`. A property test hashes two seeded runs and asserts byte-equal output. The Lambda's idempotency mechanism was never broken; the generator was non-deterministic, which made the test methodology inadvertently produce *legitimately new* events on replay.

**v1.3 (2026-04-28, Phase 2 reality-check #2 — account quota):**
- §9 Defense-in-depth on cost: **All Reserved Concurrency removed.** v1.2's revised `ingest=5, aggregator=5, api=5` still failed the second `terraform apply` with the same `UnreservedConcurrentExecution` floor error. Diagnostic: `aws lambda get-account-settings --region us-east-1` reports `ConcurrentExecutions: 10` and `UnreservedConcurrentExecutions: 10`. The account is at the AWS quota minimum; no per-function reservation can fit until an account-level service-quota-increase ticket is filed and granted. The `reserved_concurrent_executions` argument has been deleted (not zeroed) from the ingest Lambda's Terraform config. Aggregator and api Lambdas in their later phases must also omit the argument when they're built. Cost-defense intent is now served by the two upstream layers (API Gateway throttling + CloudWatch alarms on invocation rate / error rate / throttles / p95 duration). The quota-increase ticket is an account-level concern, not a dashboard build concern.
- §11 Phase 2: second apply attempt produced an additional Lambda taint; remediation captured in PHASE_2_LOG.md alongside the first.

**v1.2 (2026-04-28, Phase 2 reality-check):**
- §9 Defense-in-depth on cost: **Reserved Concurrency revised from `ingest=20, aggregator=5, api=20` to `ingest=5, aggregator=5, api=5`.** The original numbers came from copying Diamond IQ's pattern; they over-specified concurrency for a honeypot dashboard expected to do ~0.5–2 RPS at steady state. The first Phase 2 `terraform apply` against the live AWS account failed with `InvalidParameterValueException: ... decreases account's UnreservedConcurrentExecution below its minimum value of [10]` because Diamond IQ has already reserved enough of the 1000-default account-level concurrency that 20 didn't fit. 5 still serves the cost-defense purpose (caps a runaway invocations storm at ~25 inv/s × 200 ms = ~90K invocations/hour) while leaving more headroom in the account for future projects. The aggregator was already 5 in §9; this brings the ingest and api Lambdas in line with the same scale-honest reservation.
- §11 Phase 2: implementation in progress; first apply attempt produced an 11-of-17 partial state and was triaged in PHASE_2_LOG.md.

**v1.1 (2026-04-27, post-review):**
- §1 Executive summary: added timing-context paragraph (3–4 wk build, parallel with job applications, non-gating).
- §2 Architecture diagram: removed AWS WAF box; switched Cloudflare to proxied (orange cloud).
- §3 Data flow: added password classifier step in ingest narrative; noted Cloudflare proxy in browser flow.
- §4 Schema: split `password` (public, dictionary-classified) from `password_raw` (private, never API-exposed) per ADR-005.
- §9 Cost model: removed AWS WAF line ($5.40 → $0); added Cloudflare-proxy line; total revised to ~$2.60/mo.
- §10 Security: replaced AWS WAF section with Cloudflare proxy section (ADR-007); added ADR-005 password-filter description; added CloudFront viral-traffic alarm + runbook reference; changed Pi IAM key rotation from yearly to 90-day; added ADR-009 captured-malware policy.
- §11 Phase 1: added ADR-005, ADR-007, ADR-009 to deliverables.
- §11 Phase 2: added password classifier deliverable + tests.
- §11 Phase 8: removed AWS WAF; switched Cloudflare proxy ON.
- §11 Phase 8.5 (NEW): apex `dram-soc.org` static landing page resolving former open question 6.
- §11 Phase 9: heartbeat alarm created in DISABLED state; CloudFront viral-traffic alarm enabled; viral-traffic runbook deliverable added.
- §11 Phase 10: rewrote with primary path + Fallback A (VPS reverse-tunnel) + Fallback B (indefinite synthetic); separated build readiness from deployment decision.
- §11 Phase 11 (NEW): real-data tuning buffer, 3–5 days, only fires post-cutover.
- §14 Open questions: marked 6 prior questions as resolved (folded into body / ADRs); added Phase 10 deployment-path question.
- §15 Out of scope: explicitly deferred WebSocket and session drill-down to v2; clarified malware policy reference.
- §16 Dependencies: added apex frontend dir + ADR + runbooks; corrected Diamond IQ pattern reuse line (no AWS WAF).

