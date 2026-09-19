from __future__ import annotations

import json

import pytest

from soc_elastic.clients import ApiError, Elasticsearch, Kibana, from_env

from .fakes import FakeResponse, FakeSession


def es(routes: dict | None = None) -> tuple[Elasticsearch, FakeSession]:
    s = FakeSession(routes)
    return Elasticsearch("http://127.0.0.1:9200/", "elastic", "pw", session=s), s


def test_bulk_builds_ndjson_with_ids() -> None:
    client, s = es({("POST", "/_bulk"): {"errors": False, "items": []}})
    n = client.bulk_index([("idx", "a", {"x": "é"}), ("idx", "b", {"x": 2})])
    assert n == 2
    call = s.calls[0]
    lines = call["data"].decode("utf-8").strip().split("\n")
    assert json.loads(lines[0]) == {"index": {"_index": "idx", "_id": "a"}}
    assert json.loads(lines[1]) == {"x": "é"}
    assert call["headers"]["Content-Type"] == "application/x-ndjson"
    assert s.auth == ("elastic", "pw")
    assert call["url"] == "http://127.0.0.1:9200/_bulk"


def test_bulk_empty_is_noop() -> None:
    client, s = es()
    assert client.bulk_index([]) == 0
    assert s.calls == []


def test_bulk_item_errors_raise() -> None:
    items = [{"index": {"_id": "a"}}, {"index": {"_id": "b", "error": {"type": "mapper"}}}]
    client, _ = es({("POST", "/_bulk"): {"errors": True, "items": items}})
    with pytest.raises(ApiError, match="1 bulk item"):
        client.bulk_index([("i", "a", {}), ("i", "b", {})])


def test_http_error_raises_with_status() -> None:
    client, _ = es({("PUT", "/_index_template"): FakeResponse(400, {"error": "bad"})})
    with pytest.raises(ApiError, match="400"):
        client.put_index_template("t", {})


def test_count_esql_refresh() -> None:
    client, s = es(
        {
            ("POST", "/idx/_count"): {"count": 7},
            ("POST", "/_query"): {"columns": [], "values": [[1]]},
            ("POST", "/idx/_refresh"): FakeResponse(200, None),
        }
    )
    assert client.count("idx", {"match_all": {}}) == 7
    assert s.calls[0]["json"] == {"query": {"match_all": {}}}
    assert client.esql("from x")["values"] == [[1]]
    client.refresh("idx")
    assert s.calls[-1]["url"].endswith("/idx/_refresh")


def test_kibana_sends_xsrf_and_version_headers() -> None:
    s = FakeSession({("GET", "/api/status"): {"ok": True}})
    kb = Kibana("http://127.0.0.1:5601", "elastic", "pw", session=s)
    assert kb.request("GET", "/api/status", headers={"X-Extra": "1"}) == {"ok": True}
    headers = s.calls[0]["headers"]
    assert headers["kbn-xsrf"] and headers["elastic-api-version"] and headers["X-Extra"] == "1"


def test_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ELASTIC_PASSWORD", raising=False)
    with pytest.raises(SystemExit):
        from_env(Elasticsearch, "ES_URL", "http://127.0.0.1:9200")
    monkeypatch.setenv("ELASTIC_PASSWORD", "pw")
    monkeypatch.setenv("ES_URL", "http://127.0.0.1:9999")
    client = from_env(Elasticsearch, "ES_URL", "http://127.0.0.1:9200")
    assert client.url == "http://127.0.0.1:9999"
