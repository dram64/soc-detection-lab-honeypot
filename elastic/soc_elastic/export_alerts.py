"""Export detection-engine alerts from the replay as evidence.

    python -m soc_elastic.export_alerts --out evidence

Writes:
  alerts.ndjson        every alert, trimmed to triage-relevant fields
  alerts_summary.json  per rule: alert count, distinct source IPs, event time
                       range, and a cross-check against the rule's own ES|QL
                       query run directly (expected == alerts means the engine
                       dropped nothing, e.g. to max_signals)
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from .clients import Elasticsearch, from_env

ALERTS_INDEX = ".alerts-security.alerts-default"
MAX_COMMAND = 300

_KEEP = (
    "source.ip",
    "source.geo.country_iso_code",
    "source.as.number",
    "source.as.organization.name",
    "user.name",
    "cowrie.session",
    "event.action",
    "file.name",
    "file.hash.sha256",
    "file.path",
    "destination.address",
    "destination.port",
    "timebucket",
    "event_count",
    "value_count",
)


def get(doc: dict[str, Any], dotted: str) -> Any:
    """Read a field stored either flat ("a.b") or nested ({"a": {"b": ..}})."""
    if dotted in doc:
        return doc[dotted]
    cur: Any = doc
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def techniques(threat: Iterable[dict[str, Any]] | None) -> list[str]:
    ids: set[str] = set()
    for entry in threat or []:
        for tech in entry.get("technique", []):
            subs = tech.get("subtechnique") or []
            if subs:
                ids.update(s["id"] for s in subs)
            else:
                ids.add(tech["id"])
    return sorted(ids)


def trim(alert: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "alert_id": get(alert, "kibana.alert.uuid"),
        "rule": get(alert, "kibana.alert.rule.name"),
        "rule_id": get(alert, "kibana.alert.rule.rule_id"),
        "severity": get(alert, "kibana.alert.severity"),
        "risk_score": get(alert, "kibana.alert.risk_score"),
        "attack": techniques(get(alert, "kibana.alert.rule.threat")),
        "event_time": get(alert, "kibana.alert.original_time"),
        "alert_created": get(alert, "@timestamp"),
    }
    for field in _KEEP:
        value = get(alert, field)
        if value is not None:
            out[field] = value
    cmd = get(alert, "process.command_line")
    if cmd:
        out["process.command_line"] = cmd if len(cmd) <= MAX_COMMAND else cmd[:MAX_COMMAND] + "…"
    return out


def summarize(alerts: Iterable[dict[str, Any]], expected: dict[str, int]) -> dict[str, Any]:
    rules: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"alerts": 0, "ips": set(), "first": None, "last": None}
    )
    for a in alerts:
        r = rules[a["rule_id"]]
        r["name"], r["severity"], r["attack"] = a["rule"], a["severity"], a["attack"]
        r["alerts"] += 1
        if a.get("source.ip"):
            r["ips"].add(a["source.ip"])
        t = a.get("event_time") or a.get("timebucket")
        if t:
            r["first"] = min(filter(None, [r["first"], t]))
            r["last"] = max(filter(None, [r["last"], t]))
    out = {}
    for rule_id, r in sorted(rules.items(), key=lambda kv: -kv[1]["alerts"]):
        exp = expected.get(rule_id)
        out[rule_id] = {
            "name": r["name"],
            "severity": r["severity"],
            "attack": r["attack"],
            "alerts": r["alerts"],
            "expected_from_direct_esql": exp,
            "matches_expected": exp == r["alerts"],
            "distinct_source_ips": len(r["ips"]),
            "first_event": r["first"],
            "last_event": r["last"],
        }
    return {"total_alerts": sum(v["alerts"] for v in out.values()), "rules": out}


def iter_alerts(es: Elasticsearch, page: int = 1000) -> Iterator[dict[str, Any]]:
    """All alerts, oldest first, via search_after on a stable sort."""
    after: list[Any] | None = None
    while True:
        body: dict[str, Any] = {
            "size": page,
            "sort": [{"@timestamp": "asc"}, {"kibana.alert.uuid": "asc"}],
            "query": {"match_all": {}},
        }
        if after:
            body["search_after"] = after
        hits = es.request("POST", f"/{ALERTS_INDEX}/_search", json=body)["hits"]["hits"]
        if not hits:
            return
        for h in hits:
            yield h["_source"]
        after = hits[-1]["sort"]


def expected_counts(es: Elasticsearch, queries: dict[str, str]) -> dict[str, int]:
    """Run each rule's ES|QL directly over the index: row count = expected alerts."""
    counts = {}
    for rule_id, query in queries.items():
        if "| stats " in query:
            q = f"{query} | stats n = count()"
        else:
            q = query.replace(" metadata _id, _index, _version", "") + " | stats n = count()"
        counts[rule_id] = int(es.esql(q)["values"][0][0])
    return counts


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI glue
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--out", type=Path, default=Path("evidence"))
    p.add_argument("--rules-json", type=Path, default=Path("detection-rules"))
    args = p.parse_args(argv)

    es = from_env(Elasticsearch, "ES_URL", "http://127.0.0.1:9200")
    queries = {
        (d := json.loads(f.read_text("utf-8")))["rule_id"]: d["query"]
        for f in sorted(args.rules_json.glob("*.json"))
    }
    alerts = [trim(a) for a in iter_alerts(es)]
    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "alerts.ndjson").open("w", encoding="utf-8", newline="\n") as fh:
        for a in alerts:
            fh.write(json.dumps(a, ensure_ascii=False) + "\n")
    summary = summarize(alerts, expected_counts(es, queries))
    (args.out / "alerts_summary.json").write_text(json.dumps(summary, indent=2) + "\n", "utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
