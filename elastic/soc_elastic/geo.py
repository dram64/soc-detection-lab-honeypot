"""GeoLite2 Country + ASN lookups for the replay.

Same databases and the same "unknown on any failure" behaviour as the
deployed enricher (dashboard/functions/shared/geoip.py), but it also returns
the country *name* for readable dashboards. The deployed module is left
untouched because it is live Lambda code.

GeoLite2-Country has no coordinates, so the replay records country and ASN
only, never a lat/lon. The geo map is a per-country choropleth, not a
point map.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from ipaddress import ip_address
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Geo:
    country_iso_code: str | None = None
    country_name: str | None = None
    asn: int | None = None
    as_org: str | None = None


UNKNOWN = Geo()


class GeoLookup:
    def __init__(self, country_reader: Any, asn_reader: Any) -> None:
        self._country = country_reader
        self._asn = asn_reader
        self.lookup = lru_cache(maxsize=20_000)(self._lookup)

    @classmethod
    def from_dir(cls, directory: Path) -> GeoLookup:  # pragma: no cover - needs real .mmdb
        import geoip2.database

        return cls(
            geoip2.database.Reader(str(directory / "GeoLite2-Country.mmdb")),
            geoip2.database.Reader(str(directory / "GeoLite2-ASN.mmdb")),
        )

    def _lookup(self, ip: str) -> Geo:
        try:
            ip_address(ip)
        except ValueError:
            return UNKNOWN
        iso = name = org = None
        asn = None
        try:
            c = self._country.country(ip).country
            iso, name = c.iso_code, c.name
        except Exception:
            pass
        try:
            a = self._asn.asn(ip)
            asn, org = a.autonomous_system_number, a.autonomous_system_organization
        except Exception:
            pass
        return Geo(country_iso_code=iso, country_name=name, asn=asn, as_org=org)

    def close(self) -> None:  # pragma: no cover - trivial
        for reader in (self._country, self._asn):
            close = getattr(reader, "close", None)
            if close:
                close()
