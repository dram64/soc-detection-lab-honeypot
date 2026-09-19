"""Replay the archived Cowrie dataset into Elasticsearch.

    python -m soc_elastic.load \
        --cowrie C:/tmp/cowrie-archive --haproxy C:/tmp/haproxy-archive \
        --geoip-dir ../dashboard/functions/layers/geolite2 \
        --report evidence/ingest_report.json

Two passes over the Cowrie archive (it is ~34 MB gzipped, so re-reading is
cheaper than holding 232k events in memory):
  1. collect each session's connect timestamp, then attribute sessions
     against the HAProxy index (see correlate.py);
  2. transform every event to ECS and bulk-index it.

Re-running is idempotent: document IDs are deterministic (see transform.doc_id).
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from collections.abc import Iterator
from importlib import resources
from itertools import islice
from pathlib import Path
from typing import Any

from functions.shared.haproxy_parser import HAProxyRecord, parse_record
from functions.shared.password_classifier import load_dictionary

from .archive import ReadStats, iter_records
from .clients import Elasticsearch, from_env
from .correlate import UNATTRIBUTED_NO_CONNECT, Attribution, HAProxyIndex, attribute_sessions
from .geo import GeoLookup
from .transform import doc_id, index_name, to_ecs

TEMPLATE_NAME = "cowrie-replay"
INDEX_PREFIX = "cowrie"
BATCH = 2000


def load_template() -> dict[str, Any]:
    text = resources.files("soc_elastic").joinpath("index_template.json").read_text("utf-8")
    template: dict[str, Any] = json.loads(text)
    return template


# The first ~283 droplet records (May 7, before the fluent-bit regex parser was
# live) were shipped unparsed as {"log": "<raw line>"}, and their HAProxy
# log-format still had a date token before `client=`. Same leading rsyslog
# microsecond timestamp, so they correlate exactly like parsed records.
_RAW_HAPROXY = re.compile(
    r"^(?P<time>\S+) \S+ haproxy\[\d+\]: (?:\S+ )?"
    r"client=(?P<client_ip>[0-9.]+):(?P<client_port>\d+) frontend_port=(?P<frontend_port>\d+) "
    r"duration=(?P<duration>[+-]?\d+) bytes_uploaded=(?P<bytes_uploaded>[+-]?\d+) "
    r"bytes_downloaded=(?P<bytes_downloaded>[+-]?\d+) status=(?P<status>\S+)"
)


def parse_haproxy(raw: dict[str, Any]) -> HAProxyRecord | None:
    """Production parser first; fall back to the raw `log` line shape."""
    if "client_ip" in raw:
        return parse_record(raw)
    m = _RAW_HAPROXY.match(str(raw.get("log", "")))
    return parse_record(m.groupdict()) if m else None


def build_haproxy_index(root: Path, stats: ReadStats) -> tuple[HAProxyIndex, int]:
    records, bad = [], 0
    for raw in iter_records(root, stats):
        rec = parse_haproxy(raw)
        if rec is None:
            bad += 1
        else:
            records.append(rec)
    return HAProxyIndex(records), bad


def connect_times(root: Path) -> dict[str, str]:
    """session -> earliest cowrie.session.connect timestamp."""
    out: dict[str, str] = {}
    for raw in iter_records(root):
        if raw.get("eventid") == "cowrie.session.connect":
            sid, ts = raw["session"], raw["timestamp"]
            if sid not in out or ts < out[sid]:
                out[sid] = ts
    return out


def iter_actions(
    root: Path,
    attributions: dict[str, Attribution],
    geo: GeoLookup | None,
    dictionary: frozenset[str],
    stats: ReadStats,
    summary: Counter[str],
) -> Iterator[tuple[str, str, dict[str, Any]]]:
    seen_ids: set[str] = set()
    for raw in iter_records(root, stats):
        attribution = attributions.get(raw.get("session", ""), UNATTRIBUTED_NO_CONNECT)
        doc = to_ecs(raw, attribution, geo=geo, dictionary=dictionary)
        _id = doc_id(raw)
        if _id in seen_ids:
            summary["duplicate_ids"] += 1
        seen_ids.add(_id)
        summary["events"] += 1
        summary[f"events_{attribution.status}"] += 1
        cmd = doc.get("process", {}).get("command_line")
        if cmd and len(cmd.encode()) > 8191:
            summary["commands_over_keyword_limit"] += 1
        yield index_name(INDEX_PREFIX, raw["timestamp"]), _id, doc


def batched(it: Iterator[Any], n: int) -> Iterator[list[Any]]:
    while chunk := list(islice(it, n)):
        yield chunk


def session_summary(attributions: dict[str, Attribution]) -> dict[str, Any]:
    by_status = Counter(a.status for a in attributions.values())
    ips = {a.source_ip for a in attributions.values() if a.attributed}
    return {
        "sessions": len(attributions),
        "sessions_by_status": dict(sorted(by_status.items())),
        "attributed_unique_source_ips": len(ips),
    }


def run(args: argparse.Namespace, es: Elasticsearch | None) -> dict[str, Any]:
    hp_stats = ReadStats()
    index, hp_bad = build_haproxy_index(args.haproxy, hp_stats)
    attributions = attribute_sessions(connect_times(args.cowrie), index)

    geo = GeoLookup.from_dir(args.geoip_dir) if args.geoip_dir else None  # pragma: no cover
    dictionary = load_dictionary()

    stats, summary = ReadStats(), Counter[str]()
    actions = iter_actions(args.cowrie, attributions, geo, dictionary, stats, summary)
    indexed = 0
    if es is not None:
        es.put_index_template(TEMPLATE_NAME, load_template())
    for chunk in batched(actions, BATCH):
        if es is not None:
            indexed += es.bulk_index(chunk)
    if es is not None:
        es.refresh(f"{INDEX_PREFIX}-*")

    report = {
        "cowrie_archive": {
            "files": stats.files,
            "records": stats.records,
            "malformed_lines": stats.malformed,
            "unreadable_files": len(stats.unreadable_files),
        },
        "haproxy_archive": {
            "files": hp_stats.files,
            "records": hp_stats.records,
            "unparseable_records": hp_bad,
            "unique_client_ips": len(index.unique_client_ips()),
        },
        "correlation": session_summary(attributions),
        "events": dict(sorted(summary.items())),
        "indexed": indexed,
        "dry_run": es is None,
    }
    return report


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI glue
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--cowrie", type=Path, required=True)
    p.add_argument("--haproxy", type=Path, required=True)
    p.add_argument("--geoip-dir", type=Path)
    p.add_argument("--report", type=Path)
    p.add_argument("--dry-run", action="store_true", help="transform + report, index nothing")
    args = p.parse_args(argv)

    es = None if args.dry_run else from_env(Elasticsearch, "ES_URL", "http://127.0.0.1:9200")
    report = run(args, es)
    text = json.dumps(report, indent=2)
    print(text)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
