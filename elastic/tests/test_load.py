from __future__ import annotations

import argparse
import json
from pathlib import Path

from soc_elastic.clients import Elasticsearch
from soc_elastic.load import batched, load_template, parse_haproxy, run

from .conftest import write_archive
from .fakes import FakeSession

HP_PARSED = {
    "time": "2026-05-07T10:00:00.750000+00:00",
    "client_ip": "203.0.113.5",
    "client_port": 51000,
    "frontend_port": 22,
    "duration": 10,
    "bytes_uploaded": 1,
    "bytes_downloaded": 2,
    "status": "--",
}
HP_RAW = {
    "log": "2026-05-07T09:00:00.600000+00:00 soc-honeypot-ingress haproxy[7527]: "
    "07/May/2026:09:00:00.100 client=198.51.100.7:4444 frontend_port=22 duration=1571 "
    "bytes_uploaded=1436 bytes_downloaded=1328 status=--"
}
HP_NOTICE = {
    "log": "2026-05-07T03:57:35.611715+00:00 host haproxy[7525]: [NOTICE] Reloading HAProxy"
}


def cowrie(eventid: str, session: str, ts: str, **extra: object) -> dict:
    return {
        "eventid": eventid,
        "session": session,
        "timestamp": ts,
        "src_ip": "127.0.0.1",
        "sensor": "honeypot",
        **extra,
    }


def test_parse_haproxy_handles_parsed_raw_and_noise() -> None:
    parsed = parse_haproxy(HP_PARSED)
    assert parsed is not None and parsed.client_ip == "203.0.113.5"
    raw = parse_haproxy(HP_RAW)
    assert raw is not None and (raw.client_ip, raw.client_port) == ("198.51.100.7", 4444)
    assert raw.ts == "2026-05-07T09:00:00.600000+00:00"  # rsyslog timestamp, not HAProxy's
    assert parse_haproxy(HP_NOTICE) is None
    assert parse_haproxy({}) is None


def test_template_targets_cowrie_indices_and_is_strict() -> None:
    t = load_template()
    assert t["index_patterns"] == ["cowrie-*"]
    props = t["template"]["mappings"]["properties"]
    assert t["template"]["mappings"]["dynamic"] is False
    assert props["source"]["properties"]["ip"]["type"] == "ip"
    assert "password_raw" not in json.dumps(t)


def test_batched() -> None:
    assert list(batched(iter(range(5)), 2)) == [[0, 1], [2, 3], [4]]


def _archives(tmp_path: Path) -> argparse.Namespace:
    cow, hap = tmp_path / "cowrie", tmp_path / "haproxy"
    write_archive(
        cow,
        "c.json.gz",
        [
            cowrie("cowrie.session.connect", "s1", "2026-05-07T10:00:01.000000Z"),
            cowrie("cowrie.session.connect", "s1", "2026-05-07T10:00:02.000000Z"),  # dup connect
            cowrie(
                "cowrie.login.failed",
                "s1",
                "2026-05-07T10:00:03.000000Z",
                username="root",
                password="not-in-dict",
            ),
            cowrie("cowrie.command.input", "s1", "2026-05-07T10:00:04.000000Z", input="x" * 9000),
            cowrie("cowrie.session.connect", "s2", "2026-05-07T11:00:00.000000Z"),
            cowrie("cowrie.command.input", "orphan", "2026-05-07T12:00:00.000000Z", input="id"),
            "{broken",
        ],
    )
    write_archive(hap, "h.json.gz", [HP_PARSED, HP_RAW, HP_NOTICE])
    return argparse.Namespace(cowrie=cow, haproxy=hap, geoip_dir=None)


def test_run_dry_run_reports_without_indexing(tmp_path: Path) -> None:
    report = run(_archives(tmp_path), None)
    assert report["dry_run"] is True and report["indexed"] == 0
    assert report["cowrie_archive"]["records"] == 6
    assert report["cowrie_archive"]["malformed_lines"] == 1
    assert report["haproxy_archive"]["unparseable_records"] == 1
    assert report["haproxy_archive"]["unique_client_ips"] == 2
    corr = report["correlation"]
    assert corr["sessions"] == 2
    assert corr["sessions_by_status"] == {"matched": 1, "missed": 1}
    assert corr["attributed_unique_source_ips"] == 1
    ev = report["events"]
    assert ev["events_no_connect_event"] == 1
    assert ev["commands_over_keyword_limit"] == 1
    assert "duplicate_ids" not in ev


def test_run_indexes_everything_with_template_and_refresh(tmp_path: Path) -> None:
    bodies: list[bytes] = []

    def bulk(kwargs: dict) -> dict:
        bodies.append(kwargs["data"])
        return {"errors": False, "items": []}

    s = FakeSession({("POST", "/_bulk"): bulk})
    es = Elasticsearch("http://127.0.0.1:9200", "elastic", "pw", session=s)
    report = run(_archives(tmp_path), es)
    assert report["indexed"] == 6
    methods = [(c["method"], c["url"].split("9200")[1]) for c in s.calls]
    assert methods[0] == ("PUT", "/_index_template/cowrie-replay")
    assert methods[-1] == ("POST", "/cowrie-*/_refresh")
    payload = b"".join(bodies).decode()
    assert "not-in-dict" not in payload  # ADR-005 holds end to end
    assert '"_index": "cowrie-2026.05"' in payload
