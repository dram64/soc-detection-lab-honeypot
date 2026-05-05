# ADR-003 — DynamoDB single-table design

**Status:** Accepted
**Date:** 2026-04-28
**Phase introduced:** Phase 1

## Context

The dashboard has multiple distinct data shapes that share storage:

- Raw Cowrie events (one per protocol message; 8–13 fields).
- Hourly aggregate counters (per dimension+bucket+value).
- Top-N rank items (by window and dimension).
- Daily summary items.
- Heartbeat / liveness items.

Access patterns are well-known and bounded (PROJECT_PLAN.md §4):

- All events in a session.
- All events from an IP, newest first.
- All events on a day.
- Top-N usernames / passwords / countries / ASNs in a window.
- Recent N events.
- Daily summary by date.
- Heartbeat fetch.

DynamoDB charges per item, per GSI, and per WCU/RCU consumed (or per request in on-demand mode). Multi-table designs would multiply WCU/RCU baseline costs and complicate cross-shape queries (e.g., "events plus the rolling counter for the same hour").

Diamond IQ uses single-table successfully in the same AWS account.

## Decision

**One DynamoDB table, `dram-soc-honeypot`, with overloaded keys.**

| Key | Type | Notes |
|---|---|---|
| `pk` | String | partition key |
| `sk` | String | sort key |
| `gsi1pk` / `gsi1sk` | String | GSI1: by source IP |
| `gsi2pk` / `gsi2sk` | String | GSI2: by time bucket (DAY/HOUR) |
| `gsi3pk` / `gsi3sk` | String | GSI3: top-N rank lookups |

Item shapes use prefix-discriminated keys:

- `pk = SESSION#<id>` for raw events (sk = `<ts>#<eventid>`)
- `pk = AGG#HOUR#<bucket>#<dimension>` for hourly counters
- `pk = RANK#<window>#<dimension>` for rank items
- `pk = SUMMARY#DAY` for daily summaries
- `pk = HEARTBEAT` for liveness

All GSIs project `ALL` attributes — storage is cheap relative to query convenience, and our total volume is small.

**Capacity mode:** On-demand (PAY_PER_REQUEST). Predictable low volume; no provisioned-capacity waste.
**PITR:** ON (35-day continuous backup).
**Streams:** ON with `NEW_IMAGE` view (drives the aggregator Lambda).
**TTL:** `ttl` attribute, 90 days for raw events, no TTL on aggregates.

## Consequences

**Positive:**
- Single read for "give me everything for this session" — `Query` against `pk = SESSION#<id>`.
- All access patterns served by a `Query` (never a `Scan`).
- One table to monitor, alarm, and back up.
- Cost: ~$0.55/mo at 300K writes + 700K reads + 1 GB storage including PITR.
- Streams give us the aggregator hook for free; no separate change-feed plumbing.

**Negative:**
- New developers must read this ADR + the schema map in PROJECT_PLAN.md §4 to understand the key vocabulary. Mitigation: the Pydantic models and the table-key helper module name every prefix as a constant.
- Adding a new entity type requires picking a new key prefix carefully (and documenting it). Acceptable.
- GSI write storms are a real failure mode for high-cardinality dimensions; mitigated by the rank-rebuild EventBridge schedule (PROJECT_PLAN.md §4) instead of per-write rank updates.

## Alternatives considered

1. **Multi-table design (one table per entity).** Rejected — multiplies operational surface, blocks cross-entity transactions, and roughly doubles baseline cost without improving any access pattern.
2. **Aurora Serverless v2.** Rejected — orders of magnitude more expensive at idle (~$45/mo minimum) than DynamoDB on-demand. Would blow the $50/mo cap on its own.
3. **OpenSearch Serverless.** Rejected — minimum $24/mo per OCU; query flexibility doesn't justify the cost at our access-pattern complexity.
4. **S3 + Athena only (no DynamoDB).** Rejected — Athena query latency (seconds) is too slow for live dashboard refreshes; per-query scan cost would dominate.
