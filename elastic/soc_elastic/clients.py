"""Minimal Elasticsearch / Kibana HTTP clients (requests-based).

Thin on purpose: the replay needs a handful of calls, and a plain
requests.Session is trivial to fake in tests.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from typing import Any

import requests


class ApiError(RuntimeError):
    pass


class _Base:
    def __init__(
        self,
        url: str,
        user: str,
        password: str,
        *,
        session: requests.Session | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.url = url.rstrip("/")
        self.session = session or requests.Session()
        self.session.auth = (user, password)
        self.timeout = timeout

    def request(
        self, method: str, path: str, *, ok: tuple[int, ...] = (200,), **kwargs: Any
    ) -> Any:
        resp = self.session.request(method, f"{self.url}{path}", timeout=self.timeout, **kwargs)
        if resp.status_code not in ok:
            raise ApiError(f"{method} {path} -> {resp.status_code}: {resp.text[:500]}")
        return resp.json() if resp.content else None


class Elasticsearch(_Base):
    def put_index_template(self, name: str, body: dict[str, Any]) -> None:
        self.request("PUT", f"/_index_template/{name}", json=body)

    def bulk_index(self, actions: Iterable[tuple[str, str, dict[str, Any]]]) -> int:
        """Index (index, _id, doc) triples in one _bulk call. Returns the number
        of docs accepted; raises if any item failed, reporting the first error."""
        lines: list[str] = []
        count = 0
        for index, doc_id, doc in actions:
            lines.append(json.dumps({"index": {"_index": index, "_id": doc_id}}))
            lines.append(json.dumps(doc, ensure_ascii=False))
            count += 1
        if not count:
            return 0
        body = ("\n".join(lines) + "\n").encode("utf-8")
        result = self.request(
            "POST",
            "/_bulk",
            data=body,
            headers={"Content-Type": "application/x-ndjson"},
        )
        if result.get("errors"):
            failed = [item["index"] for item in result["items"] if item["index"].get("error")]
            raise ApiError(f"{len(failed)} bulk item(s) failed; first: {failed[0]}")
        return count

    def refresh(self, index: str) -> None:
        self.request("POST", f"/{index}/_refresh")

    def count(self, index: str, query: dict[str, Any] | None = None) -> int:
        body = {"query": query} if query else None
        return int(self.request("POST", f"/{index}/_count", json=body)["count"])

    def esql(self, query: str) -> dict[str, Any]:
        result: dict[str, Any] = self.request("POST", "/_query", json={"query": query})
        return result


class Kibana(_Base):
    def request(
        self, method: str, path: str, *, ok: tuple[int, ...] = (200,), **kwargs: Any
    ) -> Any:
        headers = {"kbn-xsrf": "soc-detection-lab", "elastic-api-version": "2023-10-31"}
        headers.update(kwargs.pop("headers", {}))
        return super().request(method, path, ok=ok, headers=headers, **kwargs)


def from_env(kind: type[_Base], url_var: str, default_url: str) -> Any:
    """Build a client from ELASTIC_PASSWORD (+ optional URL override). The
    loopback-only stack always authenticates as the `elastic` superuser."""
    password = os.environ.get("ELASTIC_PASSWORD")
    if not password:
        raise SystemExit("ELASTIC_PASSWORD is not set (source elastic/.env first)")
    return kind(os.environ.get(url_var, default_url), "elastic", password)
