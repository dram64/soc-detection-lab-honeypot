# Phase 10 — Pi cutover (Fallback A) — log

**Outcome:** real attacker traffic is flowing end-to-end. Cowrie on the Pi → autossh reverse-tunnel through HAProxy on the DigitalOcean droplet → fluent-bit (both edges) → S3 → ingest Lambda with bidirectional timestamp correlation + MaxMind GeoIP → DynamoDB → API → live dashboard. Verified against test session `ddc63aaac987` (real attacker IP `104.174.33.78`, country `US`, ASN `20001` Charter Communications) **after** seven hotfixes discovered during live verification.

## Architecture decided (pre-apply)

```
attacker → DigitalOcean droplet:22 → HAProxy → droplet:127.0.0.1:2225
        → autossh -R reverse tunnel from Pi → Pi:localhost:2223 → Cowrie

shipping:
  Pi:fluent-bit  → tail cowrie.json    → s3://dram-soc-honeypot-ingest/raw/cowrie/...
  Droplet:fluent-bit → tail haproxy.log → s3://dram-soc-honeypot-ingest/raw/haproxy/...

correlation (Lambda):
  haproxy item lands in DDB at pk=HAPROXY#<minute-bucket>
  cowrie event triggers a window query [t_cowrie - 200ms, t_cowrie - 1ms]
  exactly-1 candidate → src_ip rewritten + GeoIP runs on the real IP
  zero or multiple → src_ip stays 127.0.0.1, status flagged accordingly
```

## What landed in the repo (Phase 10 commit)

### ADR-010 — fluent-bit on Pi + droplet (supersedes part of ADR-002)

[`dashboard/docs/adr/010-fluent-bit-edge-shippers.md`](adr/010-fluent-bit-edge-shippers.md). Reverses ADR-002's "JVM-class log shippers" rejection of fluent-bit (which conflated Filebeat with fluent-bit; the C-binary fluent-bit is JVM-free and ~5 MB). Adds the timestamp-window correlation primitive and the autossh re-socketing discovery as Phase 10.5 backlog (deterministic Pi-side SSH relay, gated on a measured >10% ambiguity rate over 7 days).

### Terraform — `modules/edge-shippers/`

- 2 IAM users (`dram-soc-fluentbit-pi`, `dram-soc-fluentbit-droplet`) under `/edge/` IAM path
- 2 access keys (sensitive outputs)
- 2 user policies, each scoped to `s3:PutObject` on its prefix only
- 1 SSM Parameter Store SecureString for the MaxMind GeoLite2 license key
- 1 SNS topic for edge alarms (`dram-soc-edge-alarms`, no subscriptions on first apply)
- 2 CloudWatch metric filters on the ingest Lambda log group (`CowrieObjectsProcessed`, `HaproxyObjectsProcessed` in namespace `DramSoc/Edge`)
- 2 CloudWatch alarms (`-cowrie-heartbeat-missing`, `-haproxy-heartbeat-missing`); fire when no objects ingested in a 15-min window; `treat_missing_data: breaching`

### fluent-bit configs

- `dashboard/edge/fluent-bit/pi/{fluent-bit.conf,parsers.conf,soc-fluent-bit.service}`
- `dashboard/edge/fluent-bit/droplet/{fluent-bit.conf,parsers.conf,soc-fluent-bit.service}`

Both: filesystem-backed buffer (1 GB cap), 1-min/8-MB batches, gzip, retry-forever on AWS-side failures (the local cap absorbs the queue growth; the heartbeat alarms catch a wedged ship).

### HAProxy config nudge

[`dashboard/edge/haproxy/haproxy.cfg.snippet`](../edge/haproxy/haproxy.cfg.snippet). Adds `option logasap` (flush log at accept, not at session close — without this the line lands minutes after Cowrie's session.connect and the correlation window never aligns) plus a custom `log-format` whose key=value layout matches the droplet-side fluent-bit parser regex.

The microsecond timestamp the Lambda correlates on is the LEADING rsyslog timestamp (`%Y-%m-%dT%H:%M:%S.%L%z`), not a HAProxy-internal token — HAProxy's `%ms` only reaches millisecond precision. rsyslog's `RSYSLOG_FileFormat` template gives microsecond precision for free.

### Install scripts

- `dashboard/edge/install_pi.sh`
- `dashboard/edge/install_droplet.sh`

Idempotent. Each script: creates `fluent-bit` system user/group, installs fluent-bit from the Treasure Data APT repo, drops config files, ensures `fluent-bit` user can read the source log file (group membership), installs and enables the systemd unit, restarts the service. Both warn (don't fail) when `/etc/fluent-bit/aws-credentials` is absent — the credentials must be copied separately from `terraform output -raw fluentbit_*_credentials`.

### Lambda — `functions/ingest/handler.py`

- New top-level dispatch by S3 key prefix. `raw/haproxy/...` → HAProxy parser → DDB items at `pk=HAPROXY#<bucket>`. Anything else → existing Cowrie path.
- New correlation pass on Cowrie events with `src_ip == "127.0.0.1"`: query DDB for HAProxy entries in `[ts - 200ms, ts - 1ms]`, classify result as `matched` / `missed` / `ambiguous`, rewrite `src_ip` only when matched.
- GeoIP runs on the **post-correlation** IP. ADR-010 — this is the change that makes the GeoMap render real attacker geography even though Cowrie sees only loopback.
- Per-correlation EMF metric `CorrelationCandidateCount` in namespace `DramSoc/Edge`. Gives the empirical concurrency distribution that informs whether Phase 10.5 is justified (>10% ambiguity over 7 days → ship the deterministic SSH relay).

### Schema — `functions/shared/event_dto.py` + `haproxy_parser.py`

- `StoredEvent` gains 3 fields: `correlation_status`, `correlation_candidate_count`, `correlation_candidate_ips`.
- `PublicEvent` gains 1 field (the status only — we deliberately don't expose the candidate IP list to the public API).
- New module `functions/shared/haproxy_parser.py` — parses fluent-bit's regex-extracted record into a `HAProxyRecord`, builds the DDB item shape, and provides timestamp-bucket helpers used by the correlation query.

### Tests

`tests/backend/`:
- `test_haproxy_parser.py` — 12 cases (timestamp microsecond fidelity, partition key, TTL, bucket-spanning at minute boundaries, port range)
- `test_ingest_handler.py` — 5 new cases (HAProxy ingest, single-match correlation, missed, ambiguous, real-src-ip-skips-correlation, defensive doc-test that `cowrie.src_port != haproxy.client_port`)

All 221 backend tests pass.

### Runbook

[`dashboard/docs/runbooks/edge-credential-rotation.md`](runbooks/edge-credential-rotation.md). 90-day rotation cadence; emergency-revoke procedure; verification checklist.

## What actually happened in the apply choreography

Gate 2 plan was **12 to add, 2 to change, 0 to destroy** — clean. Then live verification surfaced **seven** hotfixes that needed iteration.

### Apply 1 — initial Phase 10 plan (12 + 2)

`terraform apply phase10.tfplan` succeeded except for one resource: `aws_ssm_parameter.maxmind_license_key` was created with `value = ""` because the saved plan was generated before `TF_VAR_maxmind_license_key` was set. SSM rejects empty SecureString values. Re-ran `terraform apply -target=...maxmind_license_key` with the env var set. **No state drift; no rollback needed.** 12 of 12 edge-shippers resources + ingest Lambda update + host_router (EOL-noise) all in place.

### Hotfix 1 — droplet apt distro detection

`install_droplet.sh` originally hardcoded `https://packages.fluentbit.io/debian/${CODENAME}`. The droplet runs Ubuntu Noble; the Treasure Data vendor doesn't publish `debian/noble` builds. Fixed with a per-distro `case` statement: Ubuntu Noble/Mantic fall back to the Ubuntu-Jammy package which runs cleanly. Same fix mirrored into `install_pi.sh` for consistency.

### Hotfix 2 — `chmod 0750` for fluent-bit traversal on Pi

Adding `fluent-bit` to the Cowrie group wasn't enough — `/home/cowrie` was `0700` so the group still couldn't traverse into the log directory. `install_pi.sh` now `chmod 0750`s the home dir (idempotent; owner keeps full access).

### Hotfix 3 — Lambda URL-decoded S3 keys

`fluent-bit` writes literal `=` characters in S3 keys (`raw/cowrie/date=2026-05-07/host=pi/...`). S3 event notifications **URL-encode** these to `%3D` when delivering to Lambda, but the original `_read_object_lines` passed the key straight to `s3.get_object()`. Result: every invocation failed with `AccessDenied` calling `s3:ListBucket` — S3's confusing fallback message for "object doesn't exist + ListBucket not granted." Fixed with `urllib.parse.unquote_plus(key)` in `handler()`. Regression test `test_url_encoded_key_in_s3_event_is_decoded_before_get_object` pins it.

### Hotfix 4 — HAProxy log-format regex

`option logasap` flushes the log line at TCP-accept (correct, gives microsecond timestamps for correlation), but it also prefixes in-progress numeric values with `+` (e.g. `duration=+0`, `bytes_downloaded=+0` while the session is still open). The droplet's `parsers.conf` regex required `\d+`; updated to `[+-]?\d+`. fluent-bit silently fell back to unparsed `{"log": "..."}` records before the fix; the 8 already-shipped HAProxy objects are unrecoverable in their unparsed form.

### Hotfix 5 — Cowrie `EventId` enum loosened

The schema's `EventId` was `Literal[8 closed values]`. Cowrie 2.9.17 emits ~15 event types including `cowrie.session.params`, `cowrie.log.closed`, `cowrie.client.fingerprint`, etc. Changed to `Annotated[str, Field(pattern=r"^cowrie\.[A-Za-z0-9_.-]+$", min_length=8)]` — explicit `cowrie.*` namespace, no whitespace. Downstream rollups continue to bucket only the known subset; unknown types flow through unclassified. `test_unknown_eventid_under_cowrie_namespace_accepted` + `test_eventid_outside_cowrie_namespace_rejected` capture the new contract.

### Hotfix 6 — Pi system timezone set to UTC

Cowrie wrote timestamps as `datetime.now()` formatted with a literal `Z` suffix, but the Pi was on PDT system tz — so a 7-hour offset existed between Cowrie's *labeled* UTC and *real* UTC. The 200ms correlation window can't bridge a 7-hour delta. Fixed on the Pi with `sudo timedatectl set-timezone UTC` + `sudo systemctl restart cowrie`. Old DDB items remain mislabeled (no clean retroactive fix); new sessions write correct UTC.

### Hotfix 7 — Bidirectional timestamp-window correlation (ADR-010 design fix)

The forward correlation in `_process_cowrie_object` only worked when the HAProxy batch arrived in S3 *before* the Cowrie batch. In production, fluent-bit's 60-second flush cadence on both hosts makes arrival ordering non-deterministic — and the Pi (more events per session) tended to flush first. Result: the test session `ddc63aaac987` had **all 7 events stuck at `correlation_status=missed`** despite a real HAProxy candidate sitting in DDB only 92ms away.

Implemented **F1: backward correlation in `_process_haproxy_object`.** Each newly-written HAPROXY_CONN item triggers a GSI2 range query for SESSION events in `[haproxy_ts + 1ms, haproxy_ts + 200ms]` with `src_ip=127.0.0.1`. If exactly one session matches, all of its events get a conditional UpdateItem:

```
SET src_ip, gsi1pk, correlation_status=matched, correlation_candidate_count=1, ...,
    country, asn, asn_org   (re-run GeoIP on the post-correlation IP)
WHERE attribute_not_exists(correlation_status)
   OR correlation_status IN (missed, ambiguous)
```

The conditional prevents the "last writer wins" footgun: if forward correlation already marked an event `matched` with a different IP, the backward pass skips it (logged + counted via the new EMF metric `BackwardCorrelationOutcomes` with dimensions `result ∈ {matched_new, matched_skipped_already_matched, no_candidates, ambiguous}`).

The IAM policy for `dram-soc-ingest` was missing `dynamodb:UpdateItem` (it had `BatchWriteItem`/`PutItem`/`Query` only) — added the action so backward correlation can write. The forward pass also now writes the new correlation fields on every loopback Cowrie event regardless of match outcome.

3 new pytest cases in `test_ingest_handler.py` cover: backward-matches-pending-session, backward-skips-already-matched, no-candidates-no-ops. **226 backend tests pass**; 16 of them under ingest_handler exercise the bidirectional correlation matrix.

## Live verification — final state

Test session `ddc63aaac987` (SSH from `104.174.33.78` to the public honeypot at port 22, all 7 events):

| Field | Value |
|---|---|
| `src_ip` | `104.174.33.78` (was `127.0.0.1`) |
| `country` | `US` (was none — backward GeoIP) |
| `asn` | `20001` (was none) |
| `asn_org` | `Charter Communications Inc` (was none) |
| `correlation_status` | `matched` (was `missed`) |
| `correlation_candidate_count` | `1` |
| `correlation_candidate_ips` | `["104.174.33.78"]` |
| `gsi1pk` | `IP#104.174.33.78` (so IP-search GSI queries find it) |

`/api/events?limit=3` returns the new schema (correlation_status surfaced to the public DTO). `/dashboard.dram-soc.org` HTTP 200. Both heartbeat alarms returned to OK after their first 15-min trip during the install window. EMF metric `BackwardCorrelationOutcomes` is publishing.

### Cowrie–HAProxy delta on the live test

| | |
|---|---|
| Cowrie `cowrie.session.connect` ts | `2026-05-07T05:13:53.241412Z` |
| HAProxy ts | `2026-05-07T05:13:53.149191+00:00` |
| **Delta** | **+92.221ms** |
| Window (`[t_cowrie - 200ms, t_cowrie - 1ms]`) | `[05:13:53.041412, 05:13:53.240412]` |
| In-window? | ✓ |

The 200ms window is correct-sized for the SSH-handshake latency over the autossh tunnel. We'll watch `BackwardCorrelationOutcomes{result=ambiguous}` for the first week of real traffic to decide if Phase 10.5 (deterministic SSH relay) is justified.

### Hotfix 8 — Forward per-session inheritance (BUG 2 follow-up)

Bidirectional correlation as shipped (Hotfix 7) only updates SESSION events that exist in DDB at the moment the HAProxy entry is processed. In production, Cowrie sessions split across multiple fluent-bit batches: connect + version land in batch A, login.failed + session.closed in batch B (~30–60 s later). The backward pass running on the HAProxy arrival catches batch A's events; batch B arrives after, and per-event forward correlation fails because the late events' timestamps fall outside the 200ms window of any HAProxy entry.

Live observation surfaced this: 169 of today's sessions had mixed status (connect matched, siblings missed). Login attempts and command captures — the highest-value attack data — were losing source attribution.

**Fix:** forward inheritance in `_process_cowrie_object`. For each event with `src_ip=127.0.0.1`, query `pk = SESSION#<sid>` first; if any prior event of the session has `correlation_status IN (matched, matched_inherited)`, inherit its `src_ip` + GeoIP (lookup at write time on the inherited IP). Per-batch session→IP cache avoids redundant DDB queries when many events of one session arrive in a single batch.

Distinct status `matched_inherited` (not `matched`) preserves empirical visibility — we can measure the inheritance rate vs primary timestamp-match rate via the new `BackwardCorrelationOutcomes{result=inherited}` EMF metric. Dashboard widgets treat both statuses as semantically equivalent (both are real attributed IPs).

Edge cases (chain-attribution, cross-attacker session-id collisions, race with concurrent backward pass, non-arriving HAProxy entry) are documented in the BUG 2 Gate-1.5 surface and verified with 3 new pytest cases in `test_ingest_handler.py`.

### Hotfix 9 — Empirical window-tuning + healthz config exposure

Within hours of Hotfix 8 deploying, three real bot-scanner sessions arrived with handshake-completion latencies of 234–275ms — past the 200ms `CORRELATION_WINDOW_US`. With no primary match on the connect event, forward inheritance had nothing to inherit from. Every event of every recent session was `correlation_status=missed`.

The Gate 1 window was 200ms based on theoretical handshake latency; production data clustered at 250ms ± 25ms. Widened to **500ms** with comfortable headroom for the international-bot tail, with `BackwardCorrelationOutcomes{result=ambiguous}` as the metric to watch for false-positive concurrent attribution if the window proves too wide. ADR-010 §Empirical window-tuning captures the decision.

Same hotfix exposes `correlation_window_us` on `/api/healthz` so future tuning doesn't require AWS console access — `curl https://mlncxsr5a9.execute-api.us-east-1.amazonaws.com/api/healthz` returns the deployed value.

The phase-4-dev `version` label on `/api/healthz` was noted as a separate cleanup item (cosmetic, defer to a focused PR).

## Open follow-ups

### Phase 10.5 — Deterministic SSH-relay correlation (gated on data)

If the `BackwardCorrelationOutcomes{result=ambiguous}` rate exceeds 10% over a 7-day window, replace `autossh` on the Pi with a custom SSH client (paramiko or asyncssh) that reads `forwarded-tcpip` channel-open `(originator_addr, originator_port)` and logs `(H, P)` pairs. Lambda correlation upgrades from time-window to deterministic. Estimated 1–2 days. ADR-010 §Phase 10.5.

### MaxMind license key build cadence

The `download_geolite2.sh` script and `package_lambdas.py` rebuild the `geolite2-layer.zip` from current .mmdb files at deploy time. Each rebuild produces a different `source_code_hash`, so terraform sees the layer as "must be replaced" on every plan even when the data hasn't changed. Acceptable churn for now; Phase 9 will add a scheduled refresher Lambda that handles the rebuild cleanly out-of-band.

### `aws_lambda_layer_version` always-replace plan diff

Related to the above. The user can run `terraform apply` after a fresh `download_geolite2.sh` to push a new layer version + attach it to the ingest Lambda; or skip the apply and let the deployed layer stay in place until the data is stale. State will reconcile next time someone applies with a fresh layer build.

## Credential rotations

| Date | Host | Reason | Notes |
|---|---|---|---|
| _pending_ | Pi | accelerated one-time | AWS access key `AKIAU35YERIIJXYDFHF6` echoed in chat 2026-05-07; rotate within 7 days per `runbooks/edge-credential-rotation.md` |
| _pending_ | Droplet | accelerated one-time | AWS access key `AKIAU35YERIIKOGZX6B3` echoed in chat 2026-05-07; rotate within 7 days |
| _pending_ | MaxMind | accelerated one-time | License key echoed in chat; rotate via the MaxMind console + `aws ssm put-parameter --overwrite` within 7 days |
