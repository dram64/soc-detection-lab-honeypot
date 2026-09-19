from __future__ import annotations

from soc_elastic.clients import Elasticsearch
from soc_elastic.export_alerts import (
    MAX_COMMAND,
    expected_counts,
    get,
    iter_alerts,
    summarize,
    techniques,
    trim,
)

from .fakes import FakeSession

THREAT = [
    {
        "tactic": {"id": "TA0003"},
        "technique": [{"id": "T1098", "subtechnique": [{"id": "T1098.004"}]}],
    },
    {"tactic": {"id": "TA0011"}, "technique": [{"id": "T1090", "subtechnique": []}]},
]


def per_event_alert() -> dict:
    return {
        "kibana.alert.uuid": "a1",
        "kibana.alert.rule.name": "[Sigma] Implant",
        "kibana.alert.rule.rule_id": "r-implant",
        "kibana.alert.severity": "high",
        "kibana.alert.risk_score": 73,
        "kibana.alert.rule.threat": THREAT,
        "kibana.alert.original_time": "2026-05-10T12:00:01.000Z",
        "@timestamp": "2026-09-19T09:00:00.000Z",
        "source": {"ip": "203.0.113.5", "geo": {"country_iso_code": "NL"}},
        "process": {"command_line": "x" * (MAX_COMMAND + 50)},
        "cowrie": {"session": "abc"},
    }


def test_get_reads_flat_and_nested() -> None:
    doc = {"a.b": 1, "c": {"d": {"e": 2}}}
    assert get(doc, "a.b") == 1
    assert get(doc, "c.d.e") == 2
    assert get(doc, "c.x") is None
    assert get({"c": 5}, "c.d") is None


def test_techniques_prefers_subtechniques() -> None:
    assert techniques(THREAT) == ["T1090", "T1098.004"]
    assert techniques(None) == []


def test_trim_per_event_alert_truncates_command() -> None:
    t = trim(per_event_alert())
    assert t["rule_id"] == "r-implant" and t["attack"] == ["T1090", "T1098.004"]
    assert t["source.ip"] == "203.0.113.5"
    assert t["source.geo.country_iso_code"] == "NL"
    assert t["cowrie.session"] == "abc"
    assert len(t["process.command_line"]) == MAX_COMMAND + 1
    assert t["process.command_line"].endswith("…")


def test_trim_aggregating_alert_keeps_bucket_fields() -> None:
    alert = {
        "kibana.alert.uuid": "a2",
        "kibana.alert.rule.name": "[Sigma] Brute",
        "kibana.alert.rule.rule_id": "r-bf",
        "source.ip": "198.51.100.7",
        "timebucket": "2026-05-20T11:35:00.000Z",
        "event_count": 9,
    }
    t = trim(alert)
    assert (t["timebucket"], t["event_count"], t["event_time"]) == (
        "2026-05-20T11:35:00.000Z",
        9,
        None,
    )
    assert "process.command_line" not in t


def test_summarize_counts_ips_range_and_expectation() -> None:
    a1 = trim(per_event_alert())
    a2 = dict(a1, **{"event_time": "2026-05-11T00:00:00.000Z", "source.ip": "203.0.113.9"})
    a3 = dict(a1, **{"event_time": None, "timebucket": None, "source.ip": None})
    s = summarize([a1, a2, a3], {"r-implant": 3})
    r = s["rules"]["r-implant"]
    assert s["total_alerts"] == 3
    assert r["alerts"] == 3 and r["matches_expected"] is True
    assert r["distinct_source_ips"] == 2
    assert (r["first_event"], r["last_event"]) == (
        "2026-05-10T12:00:01.000Z",
        "2026-05-11T00:00:00.000Z",
    )
    assert summarize([a1], {})["rules"]["r-implant"]["matches_expected"] is False


def test_iter_alerts_pages_with_search_after() -> None:
    pages = iter(
        [
            {"hits": {"hits": [{"_source": {"n": 1}, "sort": [1, "a"]}]}},
            {"hits": {"hits": [{"_source": {"n": 2}, "sort": [2, "b"]}]}},
            {"hits": {"hits": []}},
        ]
    )
    s = FakeSession({("POST", "/.alerts-security"): lambda _kw: next(pages)})
    es = Elasticsearch("http://127.0.0.1:9200", "elastic", "pw", session=s)
    assert [a["n"] for a in iter_alerts(es, page=1)] == [1, 2]
    assert "search_after" not in s.calls[0]["json"]
    assert s.calls[1]["json"]["search_after"] == [1, "a"]


def test_expected_counts_strips_metadata_for_event_rules() -> None:
    s = FakeSession({("POST", "/_query"): {"values": [[42]]}})
    es = Elasticsearch("http://127.0.0.1:9200", "elastic", "pw", session=s)
    counts = expected_counts(
        es,
        {
            "event": "from cowrie-* metadata _id, _index, _version | where x",
            "agg": "from cowrie-* | where y | stats c=count() by source.ip",
        },
    )
    assert counts == {"event": 42, "agg": 42}
    sent = [c["json"]["query"] for c in s.calls]
    assert sent[0] == "from cowrie-* | where x | stats n = count()"
    assert sent[1].endswith("by source.ip | stats n = count()")
