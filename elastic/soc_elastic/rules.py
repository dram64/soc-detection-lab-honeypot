"""Sigma rules -> Kibana Security detection rules (ES|QL).

pySigma does the part it is good at: turning each rule's detection logic,
correlations included, into an ES|QL query through the repo's Cowrie->ECS
pipeline (sigma/pipelines/cowrie_ecs.yml). This module builds the Detection
Engine payload around that query, instead of using pySigma's `siem_rule`
output format, for two reasons:

  * ATT&CK mapping. pySigma's formatter pairs tactic tags and technique tags
    by list position, which silently drops or mis-pairs them when a rule
    carries two techniques. Here each technique is placed under the tactic(s)
    ATT&CK actually assigns it, using the ATT&CK data bundled with pySigma
    (v19.2 at the time of writing).
  * Replay window. These rules are run against a historical dataset, so the
    lookback (`from`) has to cover May 6-21, 2026 rather than one schedule
    interval.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sigma.backends.elasticsearch import ESQLBackend
from sigma.collection import SigmaCollection
from sigma.correlations import SigmaCorrelationRule
from sigma.data.mitre_attack import (
    mitre_attack_tactics,
    mitre_attack_techniques,
    mitre_attack_techniques_tactics_mapping,
    mitre_attack_version,
)
from sigma.processing.pipeline import ProcessingPipeline
from sigma.rule import SigmaRule

ATTACK_VERSION = mitre_attack_version

# Sigma level -> (Kibana severity, risk score). Risk scores follow the
# convention used by Elastic's prebuilt rules.
SEVERITY: dict[str, tuple[str, int]] = {
    "informational": ("low", 21),
    "low": ("low", 21),
    "medium": ("medium", 47),
    "high": ("high", 73),
    "critical": ("critical", 99),
}

# Per-event rules fire once per matching document. The largest (authorized_keys
# implant) matches 1,577 events in the replay, so the cap is set above that; it
# must stay <= xpack.alerting.rules.run.alerts.max in elastic/kibana/kibana.yml.
MAX_SIGNALS = 2000

_TACTIC_IDS = {name: tid for tid, name in mitre_attack_tactics.items()}


class RuleConversionError(ValueError):
    pass


@dataclass(frozen=True)
class DeployableRule:
    rule_id: str
    name: str
    description: str
    query: str
    severity: str
    risk_score: int
    threat: list[dict[str, Any]]
    tags: list[str]
    references: list[str]
    false_positives: list[str]
    sigma_status: str
    sigma_level: str
    aggregating: bool
    techniques: list[str] = field(default_factory=list)

    def payload(
        self, *, lookback: str, interval: str = "24h", enabled: bool = False
    ) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "name": self.name,
            "description": self.description,
            "type": "esql",
            "language": "esql",
            "query": self.query,
            "severity": self.severity,
            "risk_score": self.risk_score,
            "from": lookback,
            "to": "now",
            "interval": interval,
            "enabled": enabled,
            "max_signals": MAX_SIGNALS,
            "threat": self.threat,
            "tags": self.tags,
            "references": self.references,
            "false_positives": self.false_positives,
            "author": ["dram64"],
            "license": "MIT",
            "meta": {
                "source": "sigma",
                "sigma_status": self.sigma_status,
                "attack_version": ATTACK_VERSION,
            },
        }


def _tactic_display(name: str) -> str:
    words = name.split("-")
    return " ".join(w if w == "and" else w.capitalize() for w in words)


def _technique_ref(tid: str) -> str:
    return f"https://attack.mitre.org/techniques/{tid.replace('.', '/')}/"


def threat_from_tags(tags: Iterable[str]) -> list[dict[str, Any]]:
    """Build Kibana `threat` entries from Sigma `attack.*` tags.

    Each technique goes under every tactic that is both tagged on the rule and
    assigned to that technique by ATT&CK. If the rule tags none of the
    technique's tactics, all of ATT&CK's tactics for it are used. Unknown
    technique IDs raise, so a typo can't silently vanish from the mapping.
    """
    names = [t.split(".", 1)[1].lower() for t in tags if t.lower().startswith("attack.")]
    tactic_tags = [n for n in names if n in _TACTIC_IDS]
    techniques = [n.upper() for n in names if n[:1] == "t" and n[1:5].isdigit()]

    by_tactic: dict[str, dict[str, set[str]]] = {}
    for tech in techniques:
        if tech not in mitre_attack_techniques:
            raise RuleConversionError(f"unknown ATT&CK technique {tech} (ATT&CK v{ATTACK_VERSION})")
        mapped = mitre_attack_techniques_tactics_mapping.get(tech, [])
        chosen = [t for t in tactic_tags if t in mapped] or list(mapped)
        parent = tech.split(".")[0]
        for tactic in chosen:
            subs = by_tactic.setdefault(tactic, {}).setdefault(parent, set())
            if "." in tech:
                subs.add(tech)

    threat = []
    for tactic, techs in by_tactic.items():
        tid = _TACTIC_IDS[tactic]
        threat.append(
            {
                "framework": "MITRE ATT&CK",
                "tactic": {
                    "id": tid,
                    "name": _tactic_display(tactic),
                    "reference": f"https://attack.mitre.org/tactics/{tid}/",
                },
                "technique": [
                    {
                        "id": parent,
                        "name": mitre_attack_techniques[parent],
                        "reference": _technique_ref(parent),
                        "subtechnique": [
                            {
                                "id": sub,
                                "name": mitre_attack_techniques[sub],
                                "reference": _technique_ref(sub),
                            }
                            for sub in sorted(subs)
                        ],
                    }
                    for parent, subs in sorted(techs.items())
                ],
            }
        )
    return threat


def load_pipeline(path: Path) -> ProcessingPipeline:
    return ProcessingPipeline.from_yaml(path.read_text(encoding="utf-8"))


def load_rules(paths: Iterable[Path]) -> SigmaCollection:
    collection = SigmaCollection.load_ruleset([str(p) for p in paths])
    collection.resolve_rule_references()
    return collection


def convert(collection: SigmaCollection, pipeline: ProcessingPipeline) -> list[DeployableRule]:
    """Every rule that produces output. Base rules referenced by a correlation
    (Sigma `generate: false`, the default) produce none and are skipped."""
    backend = ESQLBackend(processing_pipeline=pipeline)
    out: list[DeployableRule] = []
    for rule in collection:
        if isinstance(rule, SigmaCorrelationRule):
            queries = backend.convert_correlation_rule(rule)
        else:
            assert isinstance(rule, SigmaRule)
            queries = backend.convert_rule(rule)
        if not queries:
            continue
        if len(queries) != 1:
            raise RuleConversionError(f"{rule.title}: expected 1 query, got {len(queries)}")
        query = str(queries[0])
        level = rule.level.name.lower() if rule.level else "low"
        severity, risk = SEVERITY[level]
        tags = [f"{t.namespace}.{t.name}" for t in rule.tags]
        techniques = sorted(t.split(".", 1)[1].upper() for t in tags if t.startswith("attack.t"))
        status = rule.status.name.lower() if rule.status else "unknown"
        out.append(
            DeployableRule(
                rule_id=str(rule.id),
                name=f"[Sigma] {rule.title}",
                description=(rule.description or rule.title).strip(),
                query=query,
                severity=severity,
                risk_score=risk,
                threat=threat_from_tags(tags),
                tags=["Sigma", "Cowrie", "Phase 2 replay", f"sigma-status:{status}", *techniques],
                references=list(rule.references),
                false_positives=list(rule.falsepositives),
                sigma_status=status,
                sigma_level=level,
                aggregating="| stats " in query,
                techniques=techniques,
            )
        )
    return out
