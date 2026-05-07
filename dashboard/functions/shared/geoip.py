"""GeoIP enrichment using MaxMind GeoLite2 (Country + ASN).

The Lambda layer is built at deploy time by `download_geolite2.sh`, which
fetches the .mmdb files using a MaxMind license key from the deployer's
environment. The .mmdb files are NOT committed to git (license terms +
binary size).

At runtime, the enricher opens both readers once at cold start and caches
results in an LRU (~10K entries) to avoid hot-IP lookup overhead. On any
lookup error — unknown IP, malformed IP, reader error — the enricher
returns a `GeoIPLookup` with all fields set to `None`. The ingest pipeline
treats unknown enrichments as "unknown" rather than failing the event.

Imports of the optional `geoip2` library are deferred so that test
environments without it (and without the .mmdb files) can still load this
module to exercise the public API via fakes.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from functools import lru_cache
from ipaddress import ip_address
from pathlib import Path
from typing import Protocol


class AddressNotFoundError(Exception):
    """Raised when an IP isn't in the GeoIP database.

    Mirrors `geoip2.errors.AddressNotFoundError` but is defined locally so
    code paths can `except` it without importing geoip2 directly.
    """


@dataclass(frozen=True)
class GeoIPLookup:
    country: str | None
    asn: int | None
    asn_org: str | None


class _CountryReaderProto(Protocol):
    def country(self, ip: str): ...
    def close(self) -> None: ...


class _AsnReaderProto(Protocol):
    def asn(self, ip: str): ...
    def close(self) -> None: ...


_UNKNOWN = GeoIPLookup(country=None, asn=None, asn_org=None)


def _open_real_readers(
    country_path: Path, asn_path: Path
) -> tuple[_CountryReaderProto, _AsnReaderProto]:
    # Imported lazily so test environments without geoip2 still import this module.
    import geoip2.database  # type: ignore[import-not-found]
    import geoip2.errors  # type: ignore[import-not-found]

    # Re-export geoip2's AddressNotFoundError as the module-local one so
    # exception handling is consistent regardless of source.
    global AddressNotFoundError
    AddressNotFoundError = geoip2.errors.AddressNotFoundError  # type: ignore[misc]

    country_reader = geoip2.database.Reader(str(country_path))
    asn_reader = geoip2.database.Reader(str(asn_path))
    return country_reader, asn_reader


class GeoIPEnricher:
    """Composable GeoIP enricher backed by MaxMind GeoLite2.

    Production usage:
        enricher = GeoIPEnricher.from_layer()

    Test usage:
        enricher = GeoIPEnricher(country_reader=fake1, asn_reader=fake2)
    """

    def __init__(
        self,
        *,
        country_reader: _CountryReaderProto,
        asn_reader: _AsnReaderProto,
    ) -> None:
        self._country_reader = country_reader
        self._asn_reader = asn_reader
        self._closed = False
        # Per-instance LRU; preserves cache hits across many events in one
        # invocation and across warm invocations.
        self._cached_enrich = lru_cache(maxsize=10_000)(self._enrich_uncached)

    @classmethod
    def from_layer(
        cls,
        *,
        country_path: Path | None = None,
        asn_path: Path | None = None,
    ) -> GeoIPEnricher:
        country_path = country_path or Path("/opt/geolite2/GeoLite2-Country.mmdb")
        asn_path = asn_path or Path("/opt/geolite2/GeoLite2-ASN.mmdb")
        country_reader, asn_reader = _open_real_readers(country_path, asn_path)
        return cls(country_reader=country_reader, asn_reader=asn_reader)

    def enrich(self, ip: str) -> GeoIPLookup:
        return self._cached_enrich(ip)

    def _enrich_uncached(self, ip: str) -> GeoIPLookup:
        try:
            ip_address(ip)
        except ValueError:
            return _UNKNOWN

        country: str | None = None
        asn: int | None = None
        asn_org: str | None = None
        try:
            country_resp = self._country_reader.country(ip)
            country = country_resp.country.iso_code
        except AddressNotFoundError:
            pass
        except Exception:
            # Defensive: any reader failure → unknown for that field.
            pass
        try:
            asn_resp = self._asn_reader.asn(ip)
            asn = asn_resp.autonomous_system_number
            asn_org = asn_resp.autonomous_system_organization
        except AddressNotFoundError:
            pass
        except Exception:
            pass
        return GeoIPLookup(country=country, asn=asn, asn_org=asn_org)

    def close(self) -> None:
        if self._closed:
            return
        with contextlib.suppress(Exception):
            self._country_reader.close()
        with contextlib.suppress(Exception):
            self._asn_reader.close()
        self._closed = True
