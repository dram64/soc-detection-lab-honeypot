from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

import pytest
from functions.shared.haproxy_parser import HAProxyRecord, cowrie_ts_to_us


def write_archive(root: Path, name: str, lines: list[Any]) -> Path:
    """Write one fluent-bit style gz NDJSON batch; str items are written verbatim."""
    path = root / "date=2026-05-07" / "host=x" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        for item in lines:
            fh.write((item if isinstance(item, str) else json.dumps(item)) + "\n")
    return path


def hp(ts: str, ip: str, port: int = 40000) -> HAProxyRecord:
    """HAProxy record at an ISO timestamp ('...Z')."""
    return HAProxyRecord(
        ts=ts.replace("Z", "+00:00"),
        ts_us=cowrie_ts_to_us(ts),
        client_ip=ip,
        client_port=port,
        frontend_port=22,
        duration=0,
        bytes_uploaded=0,
        bytes_downloaded=0,
        status="--",
    )


class FakeCountry:
    def __init__(self, table: dict[str, tuple[str, str]]) -> None:
        self.table = table

    def country(self, ip: str) -> Any:
        if ip not in self.table:
            raise KeyError(ip)
        iso, name = self.table[ip]
        return type("R", (), {"country": type("C", (), {"iso_code": iso, "name": name})()})()


class FakeAsn:
    def __init__(self, table: dict[str, tuple[int, str]]) -> None:
        self.table = table

    def asn(self, ip: str) -> Any:
        if ip not in self.table:
            raise KeyError(ip)
        num, org = self.table[ip]
        return type(
            "A", (), {"autonomous_system_number": num, "autonomous_system_organization": org}
        )()


@pytest.fixture
def dictionary() -> frozenset[str]:
    return frozenset({"123456", "admin", "password"})
