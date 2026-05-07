"""HAProxy connection log → DDB item shape.

The droplet's fluent-bit emits one JSON record per HAProxy frontend
connection (parser config: dashboard/edge/fluent-bit/droplet/parsers.conf).
Each record looks like:

    {
      "time":             "2026-05-07T00:55:01.948594+00:00",
      "host":             "soc-honeypot-ingress",
      "process":          "haproxy",
      "pid":              12345,
      "client_ip":        "104.174.33.78",
      "client_port":      8728,
      "frontend_port":    22,
      "duration":         67180,
      "bytes_uploaded":   2169,
      "bytes_downloaded": 1880,
      "status":           "cD",
      "fluent_host":      "droplet",
      "fluent_source":    "haproxy"
    }

The `time` field carries microsecond precision via rsyslog's
RSYSLOG_FileFormat template. It IS the load-bearing key for the
correlation window (ADR-010 §Decision).

This module:
  * Parses the timestamp string into an aware UTC datetime + integer
    microseconds-since-epoch (the form the correlation function uses).
  * Builds the DDB item under the `HAPROXY#YYYY-MM-DDTHH:MM` partition.

The DDB schema:

    pk = HAPROXY#YYYY-MM-DDTHH:MM    (1-minute time bucket)
    sk = <iso microsecond ts>#<client_port>
    type = HAPROXY_CONN
    ts                  : str (full microsecond ISO)
    ts_us               : int (microseconds since epoch — for fast in-Python
                                window math without re-parsing)
    client_ip           : str
    client_port         : int
    frontend_port       : int
    duration            : int
    bytes_uploaded      : int
    bytes_downloaded    : int
    status              : str
    ttl                 : int (90 days from now per ADR-010 / lifecycle rule)

Look-up shape (driven by the Lambda correlation):
  Query partition HAPROXY#<bucket>, filter sk between (ts-200ms, ts-1ms).
  For events near a bucket boundary the caller queries 2 buckets.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any


@dataclass(frozen=True)
class HAProxyRecord:
    ts: str  # ISO 8601 microsecond UTC e.g. "2026-05-07T00:55:01.948594+00:00"
    ts_us: int  # microseconds since epoch
    client_ip: str
    client_port: int
    frontend_port: int
    duration: int
    bytes_uploaded: int
    bytes_downloaded: int
    status: str

    @property
    def bucket(self) -> str:
        """Minute-resolution time-bucket key, e.g. `2026-05-07T00:55`."""
        return self.ts[:16]


def parse_record(raw: dict[str, Any]) -> HAProxyRecord | None:
    """Parse one fluent-bit-emitted JSON record. Returns None on malformed
    input — the caller drops malformed records to a counter rather than
    failing the whole batch.
    """
    try:
        time_str = str(raw["time"])
        # Normalize "+00:00" / "Z" suffixes; Python's fromisoformat accepts
        # both as of 3.11, but we strip the explicit-numeric form to "Z" to
        # keep the stored ts byte-stable across writers.
        dt = datetime.fromisoformat(time_str)
        dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
        ts_iso = dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond:06d}+00:00"
        ts_us = int(dt.timestamp() * 1_000_000)

        return HAProxyRecord(
            ts=ts_iso,
            ts_us=ts_us,
            client_ip=str(raw["client_ip"]),
            client_port=int(raw["client_port"]),
            frontend_port=int(raw["frontend_port"]),
            duration=int(raw.get("duration", 0)),
            bytes_uploaded=int(raw.get("bytes_uploaded", 0)),
            bytes_downloaded=int(raw.get("bytes_downloaded", 0)),
            status=str(raw.get("status", "")),
        )
    except (KeyError, TypeError, ValueError):
        return None


def to_ddb_item(rec: HAProxyRecord, *, ttl_days: int = 90) -> dict[str, Any]:
    """Build the DynamoDB item for the HAProxy connection record."""
    expires = datetime.fromtimestamp(rec.ts_us / 1_000_000, tz=UTC) + timedelta(days=ttl_days)
    return {
        "pk": f"HAPROXY#{rec.bucket}",
        "sk": f"{rec.ts}#{rec.client_port}",
        "type": "HAPROXY_CONN",
        "ts": rec.ts,
        "ts_us": rec.ts_us,
        "client_ip": rec.client_ip,
        "client_port": rec.client_port,
        "frontend_port": rec.frontend_port,
        "duration": rec.duration,
        "bytes_uploaded": rec.bytes_uploaded,
        "bytes_downloaded": rec.bytes_downloaded,
        "status": rec.status,
        "ttl": int(expires.timestamp()),
    }


def cowrie_ts_to_us(cowrie_ts: str) -> int:
    """Convert Cowrie's ISO `YYYY-MM-DDTHH:MM:SS.uuuuuuZ` timestamp into
    microseconds since epoch (matching HAProxyRecord.ts_us).
    """
    if cowrie_ts.endswith("Z"):
        cowrie_ts = cowrie_ts[:-1] + "+00:00"
    dt = datetime.fromisoformat(cowrie_ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return int(dt.timestamp() * 1_000_000)


def buckets_for_window(cowrie_ts_us: int, window_us: int = 200_000) -> list[str]:
    """Return the minute-resolution bucket keys that span the correlation
    window `[cowrie_ts_us - window_us, cowrie_ts_us]`. Most events fit in
    one bucket; events arriving within `window_us` of a minute boundary
    span two.
    """
    start_us = cowrie_ts_us - window_us
    end_us = cowrie_ts_us
    start_dt = datetime.fromtimestamp(start_us / 1_000_000, tz=UTC)
    end_dt = datetime.fromtimestamp(end_us / 1_000_000, tz=UTC)
    start_bucket = start_dt.strftime("%Y-%m-%dT%H:%M")
    end_bucket = end_dt.strftime("%Y-%m-%dT%H:%M")
    if start_bucket == end_bucket:
        return [start_bucket]
    return [start_bucket, end_bucket]
