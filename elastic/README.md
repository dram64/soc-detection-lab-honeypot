# Phase 2: offline detection & analysis stack (Elasticsearch + Kibana)

A local, single-node Elasticsearch + Kibana used to **replay the archived 14-day Cowrie run
(May 6–21, 2026)**, run the repo's Sigma rules against it as Kibana detection rules, and analyse
the results.

> **Scope, stated plainly.** This stack was built in September 2026, months after the honeypot was
> decommissioned. It did **not** run during collection, and nothing in it ingested live traffic.
> Every alert here comes from a one-time historical replay. It runs only on a workstation: every
> port binds to `127.0.0.1`, nothing is exposed, and nothing here costs money.

## What's here

| Path | What |
|---|---|
| [`docker-compose.yml`](docker-compose.yml) | Elasticsearch 9.5.4 + Kibana 9.5.4, security on, loopback-only ports, basic licence |
| [`kibana/kibana.yml`](kibana/kibana.yml) | Kibana config (encryption keys from env, telemetry off, UTC display, alert cap) |
| [`.env.example`](.env.example) | Template for the gitignored `.env` (passwords, encryption key) |
| [`soc_elastic/`](soc_elastic/) | Python package: archive reader, offline IP attribution, ECS transform, bulk loader, Sigma→Kibana rule conversion and deploy, alert export |
| [`tests/`](tests/) | pytest suite (66 tests, 99% line coverage; CI gate 90%) |
| [`detection-rules/`](detection-rules/) | The exact Detection Engine payloads that were deployed (one JSON per rule) |
| [`kibana/saved_objects/phase2_dashboards.ndjson`](kibana/saved_objects/phase2_dashboards.ndjson) | 4 dashboards + 2 data views, exported from Kibana |
| [`evidence/`](evidence/) | Ingest report, replay results, all 4,905 alerts (trimmed NDJSON), per-rule summary, screenshots |

Investigations built on this stack: [`docs/investigations/`](../docs/investigations/).

## Run it

Needs Docker (about 4 GB RAM free), Python 3.13, and the local archive of the run. The archive is **not**
in git; it's the fluent-bit batches from `s3://dram-soc-honeypot-ingest/raw/`, copied locally before
the bucket's 90-day lifecycle expired them.

```bash
cd elastic
cp .env.example .env            # set ELASTIC_PASSWORD, KIBANA_PASSWORD, KIBANA_ENCRYPTION_KEY
docker compose up -d            # es01 + one-shot setup (kibana_system password) + kibana
pip install -e ../dashboard -e ".[dev]"
set -a; . ./.env; set +a

# 1. ingest (~1 min): 231,930 events -> index cowrie-2026.05
python -m soc_elastic.load --cowrie /path/to/cowrie-archive --haproxy /path/to/haproxy-archive \
    --geoip-dir ../dashboard/functions/layers/geolite2 --report evidence/ingest_report.json

# 2. deploy the Sigma rules and replay each one once over the archived window
python -m soc_elastic.deploy_rules --out detection-rules --recreate --replay \
    --report evidence/rule_replay.json

# 3. export alerts + cross-check counts
python -m soc_elastic.export_alerts --out evidence

# 4. dashboards: Kibana -> Stack Management -> Saved objects -> Import
#    kibana/saved_objects/phase2_dashboards.ndjson
```

Kibana: <http://127.0.0.1:5601> (user `elastic`). Tear down with `docker compose down`; add `-v`
to also delete the indexed data.

The GeoLite2 `.mmdb` files come from MaxMind under their licence and are gitignored. Fetch them with
[`dashboard/functions/layers/geolite2/download_geolite2.sh`](../dashboard/functions/layers/geolite2/download_geolite2.sh).

## Why a script instead of Logstash or Filebeat's Cowrie module

The archive can't be loaded as-is, for three reasons:

1. **Every Cowrie event says `src_ip: 127.0.0.1`.** The sensor sat behind a reverse SSH tunnel
   (ADR-010), so attacker IPs have to be rebuilt by joining against a second log source.
2. **ADR-005 password handling** has to run *before* anything is indexed: the raw password is in
   `password` and repeated inside `message` for login events.
3. The ADR-005 classifier and HAProxy parser already exist as tested production code
   (`dashboard/functions/shared/`). Importing them keeps one implementation of each policy.

A Filebeat/Logstash pipeline could do the field renames but not the cross-source join. A small, tested
Python loader (about 600 lines across five modules) was the smaller, more honest tool.

## Source-IP attribution

Offline re-run of the ingest Lambda's correlation (ADR-010):

- For each session's `cowrie.session.connect`, find HAProxy connection records with
  `connect_ts − 500 ms ≤ haproxy_ts ≤ connect_ts − 1 ms` (same constants as production).
- One candidate → `matched`. Several candidates that all share one IP → `matched_same_ip`. This
  deliberately differs from the Lambda, which calls those "ambiguous": offline, all candidates are
  visible at once.
- Several candidates with different IPs → `ambiguous`; none → `missed`; before the first HAProxy
  record → `no_haproxy_coverage`. **None of these get a `source.ip`.** Candidates are kept in
  `cowrie.correlation.candidate_ips`.
- The attribution applies to every event in the session.

| Status | Sessions |
|---|---|
| matched | 34,297 |
| matched_same_ip | 659 |
| ambiguous | 545 |
| missed | 590 |
| no_haproxy_coverage (HAProxy shipping began May 7 03:53 UTC, ~7 h after Cowrie) | 349 |
| **attributed** | **34,956 / 36,440 (95.9%)**, 1,287 distinct source IPs |

**About "1,322 unique attacker IPs":** that project figure counts every client IP in the HAProxy
log, i.e. every TCP connection to the ingress, including ones that never became a Cowrie session.
The replay reproduces it exactly (1,322 after also parsing the 283 early raw-format HAProxy lines).
**1,287** of them can be tied to Cowrie sessions. Both numbers are correct; they count different things.

**Countries.** The project previously reported "84 countries". The saved output of the ip-api.com lookup
of all 1,322 IPs (`attacker_geo.json`, kept outside the repo) has 85 country *labels*, but two pairs are
duplicates ("Netherlands" / "The Netherlands", "Turkey" / "Türkiye"), which makes **83 distinct
countries**. The 84 can't be reproduced from that file, so the README now says 83. The replay uses MaxMind
GeoLite2 on the 1,287 *session-attributed* IPs and gets **80**: a different database and a different IP set.

## Field mapping (Cowrie → ECS-aligned)

Index template: [`soc_elastic/index_template.json`](soc_elastic/index_template.json) (`dynamic: false`,
so unmapped fields aren't indexed). Fields with no ECS home live under `cowrie.*`.

| Cowrie field | Indexed as | Notes |
|---|---|---|
| `timestamp` | `@timestamp` | |
| `eventid` | `event.action`, `cowrie.eventid` | plus `event.category` / `event.type` / `event.outcome` per event type |
| `src_ip` (always 127.0.0.1) | `cowrie.src_ip` | kept for provenance only |
| *(recovered)* | `source.ip`, `source.port` | from HAProxy; port is the attacker's, not the tunnel's |
| *(GeoLite2)* | `source.geo.country_iso_code`, `source.geo.country_name`, `source.as.number`, `source.as.organization.name` | country level, no coordinates |
| `username` | `user.name` | not filtered |
| `password` | `cowrie.password` | **ADR-005:** the dictionary value or `<filtered:len=N>`; the raw value is never indexed |
| `message` | `message` | **dropped** for events carrying a password (it repeats it) |
| `input` | `process.command_line` | `command.input` / `command.failed` |
| `version`, `hassh` | `cowrie.client.version`, `cowrie.client.hassh` | |
| `shasum` + `filename` / `destfile` | `file.hash.sha256`, `file.name`, `file.path` | upload/download events only (ADR-009: no binaries) |
| `shasum`, `ttylog`, `size` on `log.closed` | `cowrie.ttylog.*` | TTY-log hashes kept out of `file.hash` |
| `dst_ip` / `dst_port` on direct-tcpip | `destination.address`, `destination.ip` (if an IP), `destination.port` | |
| `data` on direct-tcpip | `cowrie.direct_tcpip.data` | truncated to 2 KB |
| `duration` | `event.duration` (ns), `cowrie.duration_s` | |
| `session`, `sensor`, `arch` | `cowrie.session`, `observer.name`, `cowrie.arch` | |
| *(not indexed)* | `event.original` | deliberately absent: the raw line contains the password |

Document IDs are `sha1(session|timestamp|eventid)`, the same key as the production Lambda, so
re-running the load overwrites instead of duplicating. The load verifies there are no ID collisions.

## Sigma → Kibana detection rules

- Rules live in [`sigma/rules/`](../sigma/rules/), written against Cowrie's own field names.
  [`sigma/pipelines/cowrie_ecs.yml`](../sigma/pipelines/cowrie_ecs.yml) maps them to the ECS fields
  above and refuses any rule whose logsource isn't `cowrie`.
- pySigma (`pysigma-backend-elasticsearch`, ES|QL target) converts detection logic **and correlation
  rules**. `soc_elastic.rules` wraps each query in a Detection Engine payload with:
  - ATT&CK threat mapping per technique, using the ATT&CK v19.2 data bundled with pySigma. pySigma's own
    `siem_rule` output pairs tactics and techniques by list position, which mis-maps multi-technique rules.
  - a lookback covering the archived window.
- **Replay mode:** each rule is enabled for **one** execution over the whole window and then disabled.
  Per-event rules deduplicate on document `_id`, but aggregating (correlation) ES|QL rules would create
  fresh alerts on every run. `--recreate` resets Kibana's per-rule state. Without it, a non-aggregating
  ES|QL rule won't re-alert on documents it already processed, even if you delete the alerts.
- **Verification:** `export_alerts` runs every rule's query directly against the index. For all 8 rules the
  alert count **equals** the direct query's row count (4,905 total), so the engine dropped nothing.

### Known caveats of the conversion

- **Case sensitivity:** pySigma's ES|QL output uses `==` / `like` on keyword fields, which is
  case-sensitive. Sigma's default is case-insensitive. That doesn't matter for these exact-string rules, but
  it would for mixed-case evasion.
- **Tumbling windows:** correlation `timespan` becomes `date_trunc` buckets, not a sliding window, so
  bursts that straddle a bucket edge can be split.
- **Alert timestamps:** alerts are stamped with the replay time (Sept 2026). Per-event alerts carry the
  attack time in `kibana.alert.original_time`. Correlation alerts carry their bucket start in an unmapped
  `timebucket` field. The dashboards' `replay-alerts` data view defines a runtime field `attack_time`
  that picks whichever exists, so the timeline shows when attacks happened.

## Dashboards

| Dashboard | Panels |
|---|---|
| Attacker origin (geo + ASN) | sessions / IPs / countries / ASNs; country choropleth (Elastic Maps Service basemap, fetched by the browser); top countries; top ASNs; attribution status |
| Credentials & commands | top usernames; top passwords (dictionary hits only, per ADR-005); logins over time by outcome; top commands; commands over time |
| Payloads (hashes, no binaries) | uploaded payloads (name + SHA-256); redirect writes (path + SHA-256); payload event types; upload names |
| Detection alerts (Sigma replay) | alert count; timeline by rule on `attack_time`; alerts per rule; severity; top source IPs across alerts |

Session counts use counts of `cowrie.session.connect` events (exactly one per session), not
`unique_count`, which is approximate above ~3,000.

## Data-handling policy (unchanged from Phase 1)

- **ADR-005:** raw non-dictionary passwords never reach Elasticsearch. That's enforced in
  `transform.py`, tested end to end, and checked on the live index: 451 distinct indexed password values,
  0 outside the dictionary or the `<filtered:len=N>` form.
- **ADR-009:** no binaries in this stack or this repo; only SHA-256s, file names and paths. (Separately, project notes record a captured-payload archive in S3 under `captured-samples/`, which is under review against ADR-009. Phase 2 never read it.)
- Attacker commands are indexed verbatim, which matches what the live dashboard already publishes.
