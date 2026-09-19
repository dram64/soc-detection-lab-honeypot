from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from soc_elastic.clients import ApiError, Kibana
from soc_elastic.deploy_rules import (
    delete_rule,
    lookback_for,
    replay,
    upsert,
    wait_for_execution,
    write_payloads,
)
from soc_elastic.rules import DeployableRule

from .fakes import FakeResponse, FakeSession

RULE = DeployableRule(
    rule_id="r-1",
    name="[Sigma] Test",
    description="d",
    query="from cowrie-* | where true",
    severity="low",
    risk_score=21,
    threat=[],
    tags=["Sigma"],
    references=[],
    false_positives=[],
    sigma_status="experimental",
    sigma_level="low",
    aggregating=False,
)


def kibana(routes: dict) -> tuple[Kibana, FakeSession]:
    s = FakeSession(routes)
    return Kibana("http://127.0.0.1:5601", "elastic", "pw", session=s), s


def test_lookback_covers_data_start_plus_slack() -> None:
    now = datetime(2026, 9, 19, 9, 0, tzinfo=UTC)
    assert lookback_for(now) == "now-139d"  # 136.4 days -> 137, +2 slack


def test_upsert_creates_when_missing_and_updates_when_present() -> None:
    kb, s = kibana({("GET", "/api/detection_engine/rules"): FakeResponse(404, {"m": "nf"})})
    assert upsert(kb, RULE.payload(lookback="now-1d")) == "created"
    assert [c["method"] for c in s.calls] == ["GET", "POST"]

    kb, s = kibana({("GET", "/api/detection_engine/rules"): {"rule_id": "r-1"}})
    assert upsert(kb, RULE.payload(lookback="now-1d")) == "updated"
    assert [c["method"] for c in s.calls] == ["GET", "PUT"]


def test_upsert_propagates_other_errors() -> None:
    kb, _ = kibana({("GET", "/api/detection_engine/rules"): FakeResponse(500, {"m": "boom"})})
    with pytest.raises(ApiError, match="500"):
        upsert(kb, RULE.payload(lookback="now-1d"))


def _rule_state(date: str | None, status: str | None) -> dict[str, Any]:
    last = {"date": date, "status": status, "message": "ok"} if status else None
    return {"execution_summary": {"last_execution": last} if last else None}


def test_wait_ignores_stale_and_running_executions_then_returns() -> None:
    after = datetime(2026, 9, 19, 9, 0, tzinfo=UTC)
    states = iter(
        [
            _rule_state(None, None),
            _rule_state("2026-09-19T08:00:00.000Z", "succeeded"),  # older run
            _rule_state("2026-09-19T09:00:05.000Z", "running"),
            _rule_state("2026-09-19T09:00:06.000Z", "succeeded"),
        ]
    )
    kb, _ = kibana({("GET", "/api/detection_engine/rules"): lambda _kw: next(states)})
    last = wait_for_execution(kb, "r-1", after, sleep=lambda _s: None)
    assert last["status"] == "succeeded" and last["date"].startswith("2026-09-19T09:00:06")


def test_wait_times_out() -> None:
    ticks = iter([0.0, 10.0])
    kb, _ = kibana({("GET", "/api/detection_engine/rules"): _rule_state(None, None)})
    last = wait_for_execution(
        kb, "r-1", datetime.now(UTC), timeout_s=5, clock=lambda: next(ticks), sleep=lambda _s: None
    )
    assert last["status"] == "timeout"


def test_replay_enables_waits_and_always_disables() -> None:
    ok = {
        "execution_summary": {
            "last_execution": {
                "date": "2999-01-01T00:00:00Z",
                "status": "succeeded",
                "message": "done",
            }
        }
    }
    kb, s = kibana({("GET", "/api/detection_engine/rules"): ok})
    results = replay(kb, [RULE], sleep=lambda _s: None)
    assert results["[Sigma] Test"]["status"] == "succeeded"
    patches = [c["json"]["enabled"] for c in s.calls if c["method"] == "PATCH"]
    assert patches == [True, False]


def test_replay_disables_even_if_polling_fails() -> None:
    kb, s = kibana({("GET", "/api/detection_engine/rules"): FakeResponse(500, {})})
    with pytest.raises(ApiError):
        replay(kb, [RULE], sleep=lambda _s: None)
    patches = [c["json"]["enabled"] for c in s.calls if c["method"] == "PATCH"]
    assert patches == [True, False]


def test_write_payloads(tmp_path: Path) -> None:
    write_payloads([RULE], tmp_path / "out", "now-139d")
    written = json.loads((tmp_path / "out" / "r-1.json").read_text("utf-8"))
    assert written["from"] == "now-139d" and written["rule_id"] == "r-1"


def test_delete_rule_tolerates_missing_and_raises_otherwise() -> None:
    kb, s = kibana({("DELETE", "/api/detection_engine/rules"): {"id": "x"}})
    assert delete_rule(kb, "r-1") is True
    assert s.calls[0]["params"] == {"rule_id": "r-1"}
    kb, _ = kibana({("DELETE", "/api/detection_engine/rules"): FakeResponse(404, {})})
    assert delete_rule(kb, "r-1") is False
    kb, _ = kibana({("DELETE", "/api/detection_engine/rules"): FakeResponse(500, {})})
    with pytest.raises(ApiError):
        delete_rule(kb, "r-1")
