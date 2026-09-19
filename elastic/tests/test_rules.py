from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from soc_elastic.rules import (
    MAX_SIGNALS,
    RuleConversionError,
    convert,
    load_pipeline,
    load_rules,
    threat_from_tags,
)

REPO = Path(__file__).resolve().parents[2]
PIPELINE = REPO / "sigma" / "pipelines" / "cowrie_ecs.yml"
RULES = REPO / "sigma" / "rules"


@pytest.fixture(scope="module")
def deployed() -> dict[str, object]:
    rules = convert(load_rules(sorted(RULES.glob("*.yml"))), load_pipeline(PIPELINE))
    return {r.rule_id: r for r in rules}


def test_repo_rules_convert_to_eight_deployable_rules(deployed: dict) -> None:
    # 6 per-event rules + 3 correlations; the 3 correlation base rules are
    # generate:false and must not deploy on their own.
    assert len(deployed) == 8
    names = {r.name for r in deployed.values()}
    assert "[Sigma] Cowrie Failed Login" not in names
    assert "[Sigma] Automated SSH Client Banner" not in names


def test_no_repo_rule_claims_stable(deployed: dict) -> None:
    assert {r.sigma_status for r in deployed.values()} <= {"test", "experimental"}


def test_queries_use_ecs_fields_and_cowrie_index(deployed: dict) -> None:
    for rule in deployed.values():
        assert rule.query.startswith("from cowrie-* ")
        for native in ("eventid", "src_ip", "username", " input"):
            assert native not in rule.query.replace("cowrie.", "")


def test_brute_force_correlation_query(deployed: dict) -> None:
    rule = deployed["a8f47e1c-9b22-4d3e-8c5a-2f9d8e1b6c47"]
    assert rule.aggregating
    assert "not source.ip is null" in rule.query
    assert "date_trunc(5minutes, @timestamp)" in rule.query
    assert "by timebucket, source.ip" in rule.query
    assert rule.query.rstrip().endswith("where event_count >= 5")
    assert (rule.severity, rule.risk_score) == ("medium", 47)


def test_implant_rule_maps_both_techniques_to_their_own_tactics(deployed: dict) -> None:
    rule = deployed["bc1c826e-f397-48e2-8288-fe41a92f3d70"]
    by_tactic = {t["tactic"]["name"]: t for t in rule.threat}
    assert set(by_tactic) == {"Persistence", "Defense Impairment"}
    persistence = by_tactic["Persistence"]["technique"][0]
    assert persistence["id"] == "T1098"
    assert persistence["subtechnique"][0]["id"] == "T1098.004"
    impair = by_tactic["Defense Impairment"]["technique"][0]
    assert impair["subtechnique"][0]["id"] == "T1222.002"
    assert rule.techniques == ["T1098.004", "T1222.002"]
    assert "T1098.004" in rule.tags


def test_payload_shape(deployed: dict) -> None:
    rule = deployed["91f0e1bb-037a-4fdf-87e1-9f0a4747fa13"]
    p = rule.payload(lookback="now-139d")
    assert p["type"] == p["language"] == "esql"
    assert (p["from"], p["to"], p["interval"]) == ("now-139d", "now", "24h")
    assert p["enabled"] is False and p["max_signals"] == MAX_SIGNALS
    assert p["meta"]["source"] == "sigma" and p["meta"]["attack_version"]
    assert p["threat"][0]["technique"][0]["id"] == "T1090"


def test_threat_falls_back_to_attack_tactics_when_none_tagged() -> None:
    threat = threat_from_tags(["attack.t1110.001"])
    assert [t["tactic"]["id"] for t in threat] == ["TA0006"]


def test_threat_tactic_display_keeps_lowercase_and() -> None:
    threat = threat_from_tags(["attack.command-and-control", "attack.t1105"])
    assert threat[0]["tactic"]["name"] == "Command and Control"
    assert threat[0]["technique"][0]["subtechnique"] == []


def test_unknown_technique_is_an_error() -> None:
    with pytest.raises(RuleConversionError, match="T9999"):
        threat_from_tags(["attack.discovery", "attack.t9999"])


def _write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


def test_pipeline_refuses_non_cowrie_rules(tmp_path: Path) -> None:
    rule = _write(
        tmp_path,
        "zeek.yml",
        """
        title: Zeek thing
        id: 2f7a4a52-6c5e-4b0a-9f34-0c1f1f3f0b11
        status: experimental
        logsource:
          product: zeek
        detection:
          sel:
            dest_port: 4444
          condition: sel
        level: low
        """,
    )
    with pytest.raises(Exception, match="only maps logsource product 'cowrie'"):
        convert(load_rules([rule]), load_pipeline(PIPELINE))


def test_rule_without_level_or_status_defaults_to_low(tmp_path: Path) -> None:
    rule = _write(
        tmp_path,
        "bare.yml",
        """
        title: Bare
        id: 5a0f3c61-2d4e-4f7b-8a1c-9e2d3b4c5d6e
        logsource:
          product: cowrie
        detection:
          sel:
            eventid: cowrie.session.connect
          condition: sel
        """,
    )
    (only,) = convert(load_rules([rule]), load_pipeline(PIPELINE))
    assert (only.severity, only.risk_score, only.sigma_status) == ("low", 21, "unknown")
    assert only.threat == [] and not only.aggregating
