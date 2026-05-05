# ADR-002 — Pi → S3 PutObject → Lambda for log shipping

**Status:** Accepted
**Date:** 2026-04-28
**Phase introduced:** Phase 1 (decision); Phase 2 (Lambda); Phase 10 (Pi-side shipper)

## Context

Cowrie writes JSON events to disk on the Pi. The dashboard runs in AWS. We need a reliable, low-cost, low-complexity transport that:

- Buffers locally on Pi network outage.
- Replays cleanly without manual surgery.
- Doesn't drop events on AWS-side back-pressure.
- Adds no licensed-software dependency on the Pi.
- Reuses patterns already validated in Diamond IQ in this AWS account.

Three options were evaluated. Full comparison is in PROJECT_PLAN.md §7.

| Option | Cost @ 10K/day | Reliability | Complexity | Replay | Diamond IQ pattern reuse |
|---|---|---|---|---|---|
| A: CloudWatch Agent → CW Logs → subscription Lambda | ~$0.08/mo | Good | Medium | Sub-filter only | No |
| **B: Pi → S3 PutObject → Lambda** | **~$0.21/mo** | **Best** | **Low** | **Re-trigger by re-upload** | **Yes** |
| C: Pi → API Gateway → Lambda | ~$0.30/mo | Worst (no buffer) | Medium | None | No |

## Decision

**Option B.** The Pi runs a small Python systemd service (`cowrie-shipper`) that:

1. Tails `/home/cowrie/cowrie/var/log/cowrie/cowrie.json`.
2. Batches events for ~60 s (or 1 MB, whichever first).
3. Gzip-compresses the batch.
4. `PutObject`s to `s3://dram-soc-honeypot-ingest/raw/YYYY/MM/DD/HH/honeypot-<epoch>.json.gz`.
5. On network failure, queues batches in `/var/lib/cowrie-shipper/queue/` (cap 1 GB) and drains on reconnect.

S3 `ObjectCreated:*` notifications trigger the `ingest-fn` Lambda. Failed parses go to an SQS DLQ; the original S3 object is retained for replay.

Filebeat is **explicitly rejected** — it adds a JVM-class dependency to the Pi and the AWS-Filebeat S3 module needs paid Elastic license tiers for some features. A 150-line Python service is more observable, debuggable, and matches the project's "everything in code, no black boxes" thesis.

## Consequences

**Positive:**
- S3's 11-nines durability removes a class of failures.
- Pi-side queue absorbs ISP outages without event loss.
- Replay = re-upload the original `.json.gz`. The idempotency key (per ADR-001) ensures no duplicates.
- Same architectural shape as Diamond IQ's S3 PutObject ingest path — engineering knowledge transfers.
- ~$0.21/mo at 10K events/day; well within budget.

**Negative:**
- Per-event latency is ~60 s (the batch interval) rather than near-real-time. Acceptable: honeypot dashboard cadence is minutes, not milliseconds. Recruiters viewing the dashboard will not notice.
- Operational responsibility split between Pi (shipper) and AWS (ingest). Mitigated by clear runbooks and the Pi heartbeat alarm (PROJECT_PLAN.md §10).

## Alternatives considered

- **Option A** (CloudWatch Agent): cheaper at scale but with worse replay semantics and unfamiliar tooling.
- **Option C** (API Gateway): synchronous, no buffer — events lost on 5xx. Rejected for reliability.
- **Kinesis Firehose**: would buffer and batch beautifully, but adds $0.029/GB ingest plus Firehose-specific delivery configuration. Overkill at our volume; rejected.
- **Self-managed Kafka**: laughable for this scale; rejected.
