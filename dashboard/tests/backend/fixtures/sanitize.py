"""Sanitize real captured Cowrie events before checking them in as test fixtures.

Phase 11A: real-attack-data fixtures lock in the actual on-the-wire shapes
the parser sees in production, so future schema tweaks can't silently
break the ingest path. The scrubbing rules below keep the fixtures
publishable on a public repo.

Rules (per the Phase 11A spec):

  * Strip `password_raw` entirely — ADR-005 boundary; never appears in
    raw Cowrie events but defensive in case a future fixture grab pulls
    from the stored DDB shape.
  * Replace any user-PC src_ip (`104.174.33.78`, the maintainer's home
    IP from test SSH connections) with `203.0.113.1` from RFC 5737's
    documentation IP block.
  * Replace any non-null `country` with `"XX"` and any non-null `asn`
    with `0` — schema/parser tests don't care about geo values; this
    keeps fixtures stable when MaxMind updates.
  * Replace any non-null `asn_org` with `"TEST"`.
  * Drop fluent-bit transport metadata (`fluent_host`, `fluent_source`)
    — the ingest handler also drops these before schema validation, so
    fixtures stay parser-relevant.
  * Keep real attacker IPs from public bot scanners — they're already
    public knowledge from passive dns + threat-intel feeds.
"""

from __future__ import annotations

from typing import Any

USER_PC_IP = "104.174.33.78"
RFC5737_TEST_IP = "203.0.113.1"


def sanitize_for_fixture(event: dict[str, Any]) -> dict[str, Any]:
    """Return a sanitized copy safe to commit as a public-repo fixture."""
    out = dict(event)

    # ADR-005 boundary
    out.pop("password_raw", None)

    # fluent-bit transport metadata — the ingest handler strips these
    # too, so they don't belong in fixture canonical shape.
    out.pop("fluent_host", None)
    out.pop("fluent_source", None)

    # Replace maintainer home IP with RFC 5737 documentation IP.
    if out.get("src_ip") == USER_PC_IP:
        out["src_ip"] = RFC5737_TEST_IP

    # Zero geo fields where present — fixtures don't drive geo behavior.
    if out.get("country") is not None:
        out["country"] = "XX"
    if out.get("asn") is not None:
        out["asn"] = 0
    if out.get("asn_org") is not None:
        out["asn_org"] = "TEST"

    return out
