"""Deploy the repo's Sigma rules to the local Kibana detection engine.

    python -m soc_elastic.deploy_rules --replay --out detection-rules

1. Convert every rule in sigma/rules/*.yml (not sigma/rules/not-deployed/)
   through the Cowrie->ECS pipeline to ES|QL (see rules.py).
2. Write each Detection Engine payload to --out as JSON (the reviewable
   record of what was deployed).
3. Create or update each rule, disabled.
4. With --replay: enable each rule once with a lookback that covers the whole
   14-day run, wait for that execution to finish, then disable it again.

Re-running the replay: Kibana's ES|QL rule type keeps per-rule task state
and will not re-alert on documents a non-aggregating rule already processed,
even if the alerts were deleted. For a clean re-run, clear the alerts index
and pass --recreate, which deletes and recreates each rule (fresh state).

Why run once and disable: this is historical data. Per-event rules deduplicate
on document _id, but aggregating (correlation) ES|QL rules create a fresh
alert per result row on every execution, so leaving them scheduled would
duplicate alerts. One execution over the full window is the replay.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .clients import ApiError, Kibana, from_env
from .rules import DeployableRule, convert, load_pipeline, load_rules

RULES_API = "/api/detection_engine/rules"
DATA_START = datetime(2026, 5, 6, tzinfo=UTC)
FINISHED = {"succeeded", "partial failure", "failed"}


def lookback_for(now: datetime, since: datetime = DATA_START, slack_days: int = 2) -> str:
    """Date-math `from` that reaches back past `since` (plus slack)."""
    days = math.ceil((now - since).total_seconds() / 86400) + slack_days
    return f"now-{days}d"


def upsert(kb: Kibana, payload: dict[str, Any]) -> str:
    try:
        kb.request("GET", RULES_API, params={"rule_id": payload["rule_id"]})
    except ApiError as exc:
        if "-> 404" not in str(exc):
            raise
        kb.request("POST", RULES_API, json=payload)
        return "created"
    kb.request("PUT", RULES_API, json=payload)
    return "updated"


def delete_rule(kb: Kibana, rule_id: str) -> bool:
    try:
        kb.request("DELETE", RULES_API, params={"rule_id": rule_id})
    except ApiError as exc:
        if "-> 404" not in str(exc):
            raise
        return False
    return True


def set_enabled(kb: Kibana, rule_id: str, enabled: bool) -> None:
    kb.request("PATCH", RULES_API, json={"rule_id": rule_id, "enabled": enabled})


def wait_for_execution(
    kb: Kibana,
    rule_id: str,
    after: datetime,
    *,
    timeout_s: float = 300,
    poll_s: float = 5,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Poll until the rule records an execution that started after `after`."""
    deadline = clock() + timeout_s
    while True:
        rule = kb.request("GET", RULES_API, params={"rule_id": rule_id})
        last = (rule.get("execution_summary") or {}).get("last_execution") or {}
        if last.get("status") in FINISHED and last.get("date"):
            when = datetime.fromisoformat(last["date"].replace("Z", "+00:00"))
            if when >= after:
                return dict(last)
        if clock() >= deadline:
            return {"status": "timeout", "message": f"no finished execution within {timeout_s}s"}
        sleep(poll_s)


def replay(kb: Kibana, rules: list[DeployableRule], **wait_kwargs: Any) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for rule in rules:
        started = datetime.now(UTC).replace(microsecond=0)
        set_enabled(kb, rule.rule_id, True)
        try:
            last = wait_for_execution(kb, rule.rule_id, started, **wait_kwargs)
        finally:
            set_enabled(kb, rule.rule_id, False)
        results[rule.name] = {
            "rule_id": rule.rule_id,
            "status": last.get("status"),
            "message": last.get("message"),
            "executed_at": last.get("date"),
        }
    return results


def write_payloads(rules: list[DeployableRule], out: Path, lookback: str) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for rule in rules:
        path = out / f"{rule.rule_id}.json"
        path.write_text(json.dumps(rule.payload(lookback=lookback), indent=2) + "\n", "utf-8")


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI glue
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    here = Path(__file__).resolve().parents[2]
    p.add_argument("--rules-dir", type=Path, default=here / "sigma" / "rules")
    p.add_argument("--pipeline", type=Path, default=here / "sigma" / "pipelines" / "cowrie_ecs.yml")
    p.add_argument("--out", type=Path, help="write Detection Engine payloads here")
    p.add_argument("--replay", action="store_true", help="run each rule once, then disable")
    p.add_argument(
        "--recreate", action="store_true", help="delete + recreate rules (resets rule state)"
    )
    p.add_argument("--report", type=Path, help="write the replay results JSON here")
    args = p.parse_args(argv)

    lookback = lookback_for(datetime.now(UTC))
    rules = convert(load_rules(sorted(args.rules_dir.glob("*.yml"))), load_pipeline(args.pipeline))
    if args.out:
        write_payloads(rules, args.out, lookback)

    kb = from_env(Kibana, "KIBANA_URL", "http://127.0.0.1:5601")
    for rule in rules:
        if args.recreate:
            delete_rule(kb, rule.rule_id)
        print(f"{upsert(kb, rule.payload(lookback=lookback)):8} {rule.name}")
    if args.replay:
        results = replay(kb, rules)
        text = json.dumps({"lookback": lookback, "rules": results}, indent=2)
        print(text)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
