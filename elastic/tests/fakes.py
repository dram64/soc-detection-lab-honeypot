from __future__ import annotations

import json
from typing import Any


class FakeResponse:
    def __init__(self, status: int, body: Any = None) -> None:
        self.status_code = status
        self._body = body
        self.content = b"" if body is None else json.dumps(body).encode()
        self.text = self.content.decode()

    def json(self) -> Any:
        return self._body


class FakeSession:
    """Records every request; answers from a (method, path-prefix) -> response table."""

    def __init__(self, routes: dict[tuple[str, str], Any] | None = None) -> None:
        self.routes = routes or {}
        self.calls: list[dict[str, Any]] = []
        self.auth: Any = None

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"method": method, "url": url, **kwargs})
        path = url.split("//", 1)[1].split("/", 1)[1]
        path = "/" + path
        for (m, prefix), resp in self.routes.items():
            if m == method and path.startswith(prefix):
                value = resp(kwargs) if callable(resp) else resp
                return value if isinstance(value, FakeResponse) else FakeResponse(200, value)
        return FakeResponse(200, {})
