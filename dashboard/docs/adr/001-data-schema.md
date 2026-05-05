# ADR-001 — Cowrie event schema as the canonical data model

**Status:** Accepted
**Date:** 2026-04-28
**Phase introduced:** Phase 1

## Context

The dashboard ingests JSON event logs produced by Cowrie, an SSH/Telnet honeypot running on a Raspberry Pi 5. Cowrie writes one JSON line per protocol event to disk. The shape of these events is the single source of truth for everything downstream: ingest parsing, DynamoDB item structure, aggregation dimensions, API response DTOs, and frontend rendering.

A real Cowrie event sample captured from the Pi:

```json
{"eventid":"cowrie.session.connect","src_ip":"192.168.1.79","src_port":3592,
 "dst_ip":"192.168.1.253","dst_port":2222,"session":"2db032f8e0b5",
 "protocol":"ssh","sensor":"honeypot",
 "uuid":"c3ccafbe-40f0-11f1-8f67-88a29e085d67",
 "timestamp":"2026-04-27T23:19:26.097161Z"}
```

Common-field invariants:

- Every event has: `eventid`, `timestamp`, `src_ip`, `session`, `sensor`.
- Most events also have: `uuid` (sensor uuid), `protocol`.
- Login events have: `username`, `password`.
- Command events have: `input`.
- File-download events have: `url`, `outfile`, `shasum`.
- Sessions are scoped by the `session` field — multiple events share the same id.
- Timestamps are ISO 8601 with microseconds and a `Z` suffix.

## Decision

The dashboard adopts the Cowrie event JSON shape as-is. We do **not** transform field names or impose a custom schema at ingest time — we preserve the source vocabulary so that:

1. Operators familiar with Cowrie can read raw S3 objects and DynamoDB items without a translation table.
2. Replay from raw S3 objects requires no version-aware shim.
3. Future Cowrie releases that add fields require only an additive schema update, not a rename.

Pydantic v2 models in `dashboard/functions/shared/cowrie_schema.py` are the **machine-readable** form of this ADR. They use a strict-by-default base with explicitly optional event-type-specific fields. The synthetic data generator produces the same shape and is validated against the same models in CI.

Two enrichments are added at ingest time without renaming source fields:

- `country`, `asn`, `asn_org` — derived from `src_ip` via MaxMind GeoLite2.
- `ingest_id` — `sha1(session|timestamp|eventid)` for idempotency.

One transformation is applied at ingest time per ADR-005:

- `password` → dictionary-classified value (or `<filtered:len=N>`).
- `password_raw` → private attribute holding the actual value when not in the dictionary; never returned by any API endpoint.

## Consequences

**Positive:**
- Replay is trivial: raw S3 objects are byte-for-byte the original Cowrie output.
- Tests use the real Cowrie shape; no risk of synthetic-vs-real divergence on field names.
- DynamoDB items are human-readable; no decoder needed to inspect them.

**Negative:**
- Field names are not always Pythonic (`eventid` not `event_id`, `src_ip` not `source_ip`). We accept this — readability against Cowrie source is more valuable than language idiom.
- If Cowrie ever renames a field, we have to update consumers explicitly (no abstraction layer protects us). Acceptable given Cowrie's stable schema history.

## Alternatives considered

1. **Renaming everything to a custom internal schema (e.g., `cowrie.session.connect` → `event_type: "session_connect"`).** Rejected — the cost (translation tables, replay shims, debugger confusion) outweighs the benefit (slight readability gain).
2. **Open Cyber Security Schema Framework (OCSF) normalization at ingest.** Rejected for v1 — OCSF is the right answer for a multi-source SOC, but this dashboard has exactly one source. Adopting OCSF here would be premature abstraction. Could be reconsidered if a second sensor type is added.
