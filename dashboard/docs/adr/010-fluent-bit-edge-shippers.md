# ADR-010 — fluent-bit on Pi + droplet, timestamp-window correlation (supersedes part of ADR-002)

**Status:** Accepted
**Date:** 2026-05-07
**Phase introduced:** Phase 10 (real Pi cutover)

## Context

Phase 10 brings real attacker traffic through the dashboard's ingest pipeline. The deployed edge layer is:

```
attacker → DigitalOcean droplet:22 → HAProxy → droplet:127.0.0.1:2225
        → autossh -R reverse tunnel from Pi → Pi:localhost:2223 → Cowrie
```

Two new realities surfaced from this topology:

1. **Two log sources, two hosts.** Cowrie's structured JSON on the Pi, HAProxy's connection log on the droplet. ADR-002 anticipated only the Pi-side Cowrie feed.
2. **Cowrie 2.9.17 doesn't actually parse PROXY protocol** despite its `enable_proxy_proto = true` config flag (verified by source-grep). Cowrie sees every connection from `127.0.0.1` (the local autossh-tunnel endpoint). The real attacker IP exists only in HAProxy's frontend log.

ADR-002 specified a custom ~150-line Python systemd shipper called `cowrie-shipper`. ADR-002 also explicitly rejected fluent-bit and Filebeat under the heading "JVM-class log shippers."

That heading conflated two very different tools. **Filebeat** is part of the Elastic stack and sits in a JVM-adjacent runtime context. **fluent-bit** is a single ~5 MB C binary with a ~10 MB resident footprint — no JVM, no runtime dependencies, fits a Pi 5 trivially. The "JVM-class" objection in ADR-002 doesn't apply to fluent-bit specifically; it was a write-up error.

Phase 10's two log sources also mean writing two custom Python shippers — exactly the boilerplate (tail file → buffer → gzip → S3 PutObject with retries) that fluent-bit exists to eliminate. Maintaining two copies of that pattern is not engineering work this project should do.

## Decision

**Use fluent-bit on both edge hosts (Pi and droplet).** Each host has its own scoped IAM user with `s3:PutObject` on its prefix only.

**S3 key layout (extends ADR-002):**
- Pi: `s3://dram-soc-honeypot-ingest/raw/cowrie/date=YYYY-MM-DD/host=pi/cowrie-<UUID>.json.gz`
- Droplet: `s3://dram-soc-honeypot-ingest/raw/haproxy/date=YYYY-MM-DD/host=droplet/haproxy-<UUID>.json.gz`

Both prefixes fall under the existing `s3:ObjectCreated:*` notification with `filter_prefix = "raw/"`, so the ingest Lambda triggers without configuration change.

**Correlation primitive: timestamp-window match.**

The naive plan was port-pair matching: HAProxy's backend-side source port equals Cowrie's `src_port`. **That assumption is wrong.** SSH `-R` port forwarding (the `autossh -R 2225:localhost:2223` tunnel) does not preserve ports across hops:

- HAProxy connects to `droplet:127.0.0.1:2225` with some ephemeral port `H`.
- The droplet's `sshd` accepts on 2225, sends a `forwarded-tcpip` channel-open through the SSH session back to the Pi.
- Pi-side `autossh` opens a fresh TCP connection to `localhost:2223` with a Pi-kernel-chosen ephemeral port `P`.
- Cowrie sees `src_port = P`, not `H`. **`P` is independent of `H`** — the two are kernel-assigned on opposite sides of an SSH tunnel that's a bytes-only transport.

The SSH protocol's `forwarded-tcpip` channel-open carries `(originator_addr, originator_port)` (HAProxy's loopback addr+port `H`) from droplet to Pi, but `autossh` doesn't surface that information to the data stream — it just opens the new TCP connection and forwards bytes. There is no port-based join across the tunnel without replacing autossh.

The remaining cross-tunnel signals are timestamps. **Strategy:** log connection acceptance at microsecond precision on both sides, match each Cowrie session to the HAProxy entry whose timestamp falls in the window `[t_cowrie - 200ms, t_cowrie - 1ms]`. Tail latency for SSH handshake + tunnel forwarding is rarely > 200ms; the window is tight to keep matched-status confidence high. If exactly one HAProxy candidate falls in the window, the Cowrie event's `src_ip` is rewritten from `127.0.0.1` to the HAProxy-logged client IP. Multiple candidates → `correlation_status: ambiguous`, IP left as `127.0.0.1`. Zero candidates → `correlation_status: missed`.

Every correlation attempt emits a CloudWatch custom metric `CorrelationCandidateCount` regardless of outcome, so the empirical concurrency distribution can be measured in production and inform whether a deterministic correlation path (Phase 10.5 below) is justified.

This supersedes the "150-line Python `cowrie-shipper`" specification in ADR-002 §Decision. The rest of ADR-002 (S3 PutObject as the transport, S3 ObjectCreated as the trigger, gzip + NDJSON line-format) stands as written.

## Consequences

**Positive:**
- One mature, hardened tool covering both log sources. ~5 MB binary, ~10 MB RAM.
- File-based buffering, retries, gzip, multi-output routing, parsers — built in. No reinventing.
- fluent-bit is the named tool on the project's resume; using it is interview-defensible.
- Configuration is declarative (`.conf` + parser files) and version-controlled.
- The correlation strategy honestly surfaces ambiguity rather than papering over it. The `correlation_status` field and `CorrelationCandidateCount` metric are themselves engineering artifacts.

**Negative:**
- Small learning curve on fluent-bit's filter and parser DSL. Accepted.
- Two static AWS access keys live on the edge hosts. Rotation cadence: 90 days. Mitigated by per-host IAM scoping (PutObject on a single prefix).
- Timestamp correlation has a measurable false-merge risk under concurrent connections. A public SSH honeypot is among the highest-concurrency targets on the internet — bot-scanner traffic can produce multiple connections within a 200ms window. We accept ~15–30% ambiguous-status events as a starting point and instrument the candidate-count distribution to revisit with hard data after one week of real traffic.

## Phase 10.5 — Deterministic correlation via custom Pi-side SSH relay

If the measured candidate-count distribution shows >10% ambiguity over a 7-day window of real attack traffic, replace `autossh` on the Pi with a small custom SSH client (paramiko or asyncssh) that:

1. Establishes the SSH session to the droplet itself.
2. Receives `forwarded-tcpip` channel-open requests, **reads `(originator_addr, originator_port)` from the SSH protocol** — which IS HAProxy's loopback addr+port `H`.
3. Logs `(timestamp, originator_port=H, pi_chosen_local_port=P)` to a file on the Pi, shipped via fluent-bit to S3.
4. Then opens the local TCP connection to `localhost:2223` (Cowrie) with port `P`.

The Lambda's correlation upgrades from time-window to a deterministic two-step join:

- HAProxy log → Pi-relay log via `H` (HAProxy's loopback source port, `%bp` in HAProxy log-format).
- Pi-relay log → Cowrie via `P` (matches Cowrie's `src_port`).

Estimated effort: 1–2 days. Triggered by data, not by schedule.

## Future work — MaxMind license storage

The MaxMind GeoLite2 license key lives in **SSM Parameter Store SecureString** for Phase 10. When the scheduled GeoIP-refresher Lambda lands (Phase 9 or later), it reads the key from SSM and rotates the layer weekly. A migration to AWS Secrets Manager is justified only if and when automated *license-key* rotation enters scope (Secrets Manager has built-in rotation hooks; SSM does not). Today, the license key is rotated annually by hand; SSM's $0/mo cost wins.

## Alternatives considered

1. **Custom Python shipper per ADR-002.** Rejected — would require writing and maintaining the same pattern twice (Pi for cowrie.json, droplet for haproxy.log) and reinventing what fluent-bit already does.
2. **CloudWatch Agent on both hosts.** Rejected — adds CloudWatch Logs storage cost, then a subscription Lambda to bridge to S3, then back to the existing S3 ingest path. More moving parts for no benefit.
3. **Filebeat (re-considered).** Rejected — same reasons ADR-002 originally gave: heavier footprint, Elastic-licensing footnotes, less Pi-friendly. ADR-002's objection holds for Filebeat specifically.
4. **vector.dev.** Considered briefly — comparable to fluent-bit, slightly newer / smaller community. Rejected on the resume-defensibility axis; fluent-bit is the named tool.
5. **Backend port-pair correlation.** Rejected — does not survive the autossh tunnel. See §Decision above.
6. **Replace autossh with custom SSH relay now.** Considered for Phase 10. Rejected for this phase as scope creep; captured as Phase 10.5, gated on measured ambiguity rate from real traffic.
7. **Defer correlation entirely.** Rejected — we have the data and can make the join we can make. Honest ambiguity flagging beats two parallel-but-uncorrelated event streams in the dashboard.

## Relationship to ADR-002

ADR-002 stays in the repo as historical record (append-only ADR convention). This ADR (010) supersedes ADR-002's §Decision paragraph that specified the custom Python shipper. The transport choice (S3 PutObject → Lambda) and the bucket layout in ADR-002 remain in force.
