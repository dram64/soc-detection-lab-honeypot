"""Tests for the GeoIP enrichment module.

We don't ship the real GeoLite2 .mmdb files in CI (license + size). Instead
the tests work against a Mock reader that returns deterministic answers, so
the module's contract — what it returns on hit, miss, error, malformed IP —
is exercised without needing maxminddb installed in CI.
"""

from __future__ import annotations

from typing import Any

import pytest

from functions.shared.geoip import GeoIPEnricher, GeoIPLookup


class FakeCountryReader:
    def __init__(self, mapping: dict[str, dict[str, Any]]):
        self._mapping = mapping
        self.calls: list[str] = []

    def country(self, ip: str):
        self.calls.append(ip)
        if ip not in self._mapping:
            from functions.shared.geoip import AddressNotFoundError

            raise AddressNotFoundError(ip)
        record = self._mapping[ip]
        # Mimic geoip2.records.Country shape
        return type(
            "Resp",
            (),
            {"country": type("Country", (), {"iso_code": record.get("iso_code")})()},
        )()

    def close(self) -> None:
        pass


class FakeAsnReader:
    def __init__(self, mapping: dict[str, dict[str, Any]]):
        self._mapping = mapping

    def asn(self, ip: str):
        if ip not in self._mapping:
            from functions.shared.geoip import AddressNotFoundError

            raise AddressNotFoundError(ip)
        record = self._mapping[ip]
        return type(
            "Resp",
            (),
            {
                "autonomous_system_number": record.get("asn"),
                "autonomous_system_organization": record.get("asn_org"),
            },
        )()

    def close(self) -> None:
        pass


@pytest.fixture
def enricher():
    country_reader = FakeCountryReader(
        {
            "1.2.3.4": {"iso_code": "US"},
            "8.8.8.8": {"iso_code": "US"},
            "203.0.113.5": {"iso_code": "DE"},
        }
    )
    asn_reader = FakeAsnReader(
        {
            "1.2.3.4": {"asn": 14061, "asn_org": "DigitalOcean LLC"},
            "8.8.8.8": {"asn": 15169, "asn_org": "Google LLC"},
            "203.0.113.5": {"asn": 24940, "asn_org": "Hetzner Online GmbH"},
        }
    )
    return GeoIPEnricher(country_reader=country_reader, asn_reader=asn_reader)


def test_enrich_known_ip(enricher):
    result = enricher.enrich("1.2.3.4")
    assert isinstance(result, GeoIPLookup)
    assert result.country == "US"
    assert result.asn == 14061
    assert result.asn_org == "DigitalOcean LLC"


def test_enrich_known_ip_de(enricher):
    result = enricher.enrich("203.0.113.5")
    assert result.country == "DE"
    assert result.asn == 24940


def test_enrich_unknown_ip_returns_unknown_marker(enricher):
    # 198.51.100.1 is in TEST-NET-2; not in our fake mapping.
    result = enricher.enrich("198.51.100.1")
    assert result.country is None
    assert result.asn is None
    assert result.asn_org is None


def test_enrich_invalid_ip_returns_unknown_marker(enricher):
    result = enricher.enrich("not-an-ip")
    assert result.country is None
    assert result.asn is None


def test_enrich_caches_results(enricher):
    enricher.enrich("1.2.3.4")
    enricher.enrich("1.2.3.4")
    enricher.enrich("1.2.3.4")
    # The fake reader records every call; if caching works the second/third
    # enrich don't hit it.
    assert enricher._country_reader.calls.count("1.2.3.4") == 1


def test_enricher_close_idempotent(enricher):
    enricher.close()
    enricher.close()  # must not raise
