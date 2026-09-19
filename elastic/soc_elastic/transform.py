"""Cowrie JSON event -> ECS-aligned Elasticsearch document.

Field mapping is documented in elastic/README.md ("Field mapping"). Custom
fields that ECS has no home for live under `cowrie.*`.

Data-handling rules enforced here (these are the reason this is code, not a
Logstash filter):
  * ADR-005: the attempted password is run through the production dictionary
    classifier. Only the public form (the dictionary hit, or
    "<filtered:len=N>") is indexed. The raw value is dropped and never reaches
    Elasticsearch. Cowrie repeats the password inside `message` for login
    events ("login attempt [user/pass] failed"), so `message` is dropped for
    every event that carries a password.
  * ADR-009: only SHA-256 + file name/path are indexed. Binaries were never in
    the archive to begin with.
  * No `event.original`: the raw line contains the unfiltered password.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from ipaddress import ip_address
from typing import Any

from functions.shared.password_classifier import classify_password

from .correlate import Attribution
from .geo import UNKNOWN, Geo, GeoLookup

ECS_VERSION = "8.17.0"
MAX_TCPIP_DATA = 2048

# eventid -> (event.category, event.type, event.outcome)
_CLASSIFICATION: dict[str, tuple[list[str], list[str], str | None]] = {
    "cowrie.login.failed": (["authentication"], ["start"], "failure"),
    "cowrie.login.success": (["authentication"], ["start"], "success"),
    "cowrie.session.connect": (["network", "session"], ["connection", "start"], None),
    "cowrie.session.closed": (["network", "session"], ["end"], None),
    "cowrie.command.input": (["process"], ["start"], None),
    "cowrie.command.failed": (["process"], ["start"], "failure"),
    "cowrie.session.file_download": (["file"], ["creation"], None),
    "cowrie.session.file_upload": (["file"], ["creation"], None),
    "cowrie.direct-tcpip.request": (["network"], ["connection"], None),
    "cowrie.direct-tcpip.data": (["network"], ["protocol"], None),
}
_DEFAULT_CLASSIFICATION: tuple[list[str], list[str], str | None] = (
    ["network"],
    ["info"],
    None,
)


def doc_id(raw: dict[str, Any]) -> str:
    """Same key as the production ingest Lambda's `_ingest_id`, so a re-run
    overwrites instead of duplicating."""
    key = f"{raw['session']}|{raw['timestamp']}|{raw['eventid']}"
    return hashlib.sha1(key.encode()).hexdigest()


def _is_ip(value: str) -> bool:
    try:
        ip_address(value)
    except ValueError:
        return False
    return True


def _drop_none(obj: Any) -> Any:
    if isinstance(obj, dict):
        cleaned = {k: _drop_none(v) for k, v in obj.items()}
        return {k: v for k, v in cleaned.items() if v not in (None, {}, [])}
    return obj


def to_ecs(
    raw: dict[str, Any],
    attribution: Attribution,
    *,
    geo: GeoLookup | None,
    dictionary: frozenset[str],
) -> dict[str, Any]:
    eventid: str = raw["eventid"]
    ts: str = raw["timestamp"]
    category, etype, outcome = _CLASSIFICATION.get(eventid, _DEFAULT_CLASSIFICATION)

    src_ip = attribution.source_ip if attribution.attributed else None
    g: Geo = geo.lookup(src_ip) if (geo and src_ip) else UNKNOWN

    has_password = "password" in raw
    public_pw, _raw_pw_discarded = classify_password(raw.get("password"), dictionary)

    duration = raw.get("duration")
    sha = raw.get("shasum")
    is_payload = eventid in ("cowrie.session.file_download", "cowrie.session.file_upload")
    is_tcpip = eventid.startswith("cowrie.direct-tcpip.")
    command = raw.get("input") if eventid.startswith("cowrie.command.") else None

    dst_addr = raw.get("dst_ip") if is_tcpip else None
    tcpip_data = raw.get("data") if is_tcpip else None
    if isinstance(tcpip_data, str) and len(tcpip_data) > MAX_TCPIP_DATA:
        tcpip_data = tcpip_data[:MAX_TCPIP_DATA]

    message = raw.get("message")
    if has_password or isinstance(message, list):
        message = None

    user = raw.get("username")
    doc: dict[str, Any] = {
        "@timestamp": ts,
        "ecs": {"version": ECS_VERSION},
        "message": message,
        "tags": ["honeypot", "cowrie", "phase2-replay"],
        "event": {
            "kind": "event",
            "module": "cowrie",
            "dataset": "cowrie.honeypot",
            "action": eventid,
            "category": category,
            "type": etype,
            "outcome": outcome,
            "duration": int(float(duration) * 1e9) if duration is not None else None,
        },
        "observer": {
            "name": raw.get("sensor"),
            "type": "honeypot",
            "product": "Cowrie",
            "vendor": "Cowrie",
        },
        "network": {"protocol": raw.get("protocol"), "transport": "tcp"},
        "source": {
            "ip": src_ip,
            "port": attribution.source_port if src_ip else None,
            "geo": {"country_iso_code": g.country_iso_code, "country_name": g.country_name},
            "as": {"number": g.asn, "organization": {"name": g.as_org}},
        },
        "destination": {
            "address": dst_addr,
            "ip": dst_addr if (dst_addr and _is_ip(dst_addr)) else None,
            "port": raw.get("dst_port") if is_tcpip else None,
        },
        "user": {"name": user},
        "process": {"command_line": command},
        "file": {
            "name": raw.get("filename") if is_payload else None,
            "path": raw.get("destfile") if is_payload else None,
            "hash": {"sha256": sha if is_payload else None},
        },
        "related": {
            "ip": [src_ip] if src_ip else None,
            "user": [user] if user else None,
            "hash": [sha] if (sha and is_payload) else None,
        },
        "cowrie": {
            "eventid": eventid,
            "session": raw.get("session"),
            "src_ip": raw.get("src_ip"),
            "password": public_pw,
            "arch": raw.get("arch"),
            "duration_s": duration,
            "outfile": raw.get("outfile") if is_payload else None,
            "duplicate": raw.get("duplicate"),
            "client": {"version": raw.get("version"), "hassh": raw.get("hassh")},
            "auth": {"type": raw.get("type"), "key_fingerprint": raw.get("fingerprint")},
            "ttylog": (
                {"path": raw.get("ttylog"), "size": raw.get("size"), "sha256": sha}
                if eventid == "cowrie.log.closed"
                else None
            ),
            "direct_tcpip": {"data": tcpip_data},
            "correlation": {
                "status": attribution.status,
                "candidate_count": len(attribution.candidate_ips) or None,
                "candidate_ips": list(attribution.candidate_ips) or None,
                "haproxy_ts": attribution.haproxy_ts,
                "delta_ms": attribution.delta_ms,
            },
        },
    }
    return _drop_none(doc)


def index_name(prefix: str, ts: str) -> str:
    """Monthly index, e.g. cowrie-2026.05."""
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return f"{prefix}-{dt:%Y.%m}"
