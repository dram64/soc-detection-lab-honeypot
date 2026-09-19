"""Offline source-IP attribution for Cowrie sessions.

Every Cowrie event in the archive carries src_ip=127.0.0.1, because the
sensor sat behind a reverse SSH tunnel (see ADR-010). The real client IP
only exists in the HAProxy connection log on the ingress droplet. The
deployed ingest Lambda joins the two with a timestamp window; this module
re-runs the same join offline over the complete archive:

  HAProxy record matches a session iff
      connect_ts - WINDOW  <=  haproxy_ts  <=  connect_ts - MIN_DELTA

with the same constants as production (500 ms window, 1 ms floor). The match
is made once per session, on its cowrie.session.connect event, and applied
to every event in that session.

Deliberate difference from production: the Lambda labels any window with
more than one HAProxy candidate "ambiguous". Offline we can see all
candidates at once, so a window whose candidates all share one IP is
attributed (status "matched_same_ip"). The attribution is not in doubt in
that case; only the specific connection is. Windows whose candidates span
different IPs stay "ambiguous" and get no source.ip. Nothing is guessed.
"""

from __future__ import annotations

import bisect
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from functions.shared.haproxy_parser import HAProxyRecord, cowrie_ts_to_us

CORRELATION_WINDOW_US = 500_000
CORRELATION_MIN_DELTA_US = 1_000

MATCHED = "matched"
MATCHED_SAME_IP = "matched_same_ip"
AMBIGUOUS = "ambiguous"
MISSED = "missed"
NO_COVERAGE = "no_haproxy_coverage"
NO_CONNECT = "no_connect_event"

ATTRIBUTED_STATUSES = frozenset({MATCHED, MATCHED_SAME_IP})


@dataclass(frozen=True)
class Attribution:
    status: str
    source_ip: str | None = None
    source_port: int | None = None
    candidate_ips: tuple[str, ...] = ()
    haproxy_ts: str | None = None
    delta_ms: float | None = None

    @property
    def attributed(self) -> bool:
        return self.status in ATTRIBUTED_STATUSES


UNATTRIBUTED_NO_CONNECT = Attribution(status=NO_CONNECT)


class HAProxyIndex:
    """HAProxy records sorted by time, for O(log n) window lookups."""

    def __init__(
        self,
        records: Iterable[HAProxyRecord],
        *,
        window_us: int = CORRELATION_WINDOW_US,
        min_delta_us: int = CORRELATION_MIN_DELTA_US,
    ) -> None:
        self._records = sorted(records, key=lambda r: r.ts_us)
        self._ts = [r.ts_us for r in self._records]
        self.window_us = window_us
        self.min_delta_us = min_delta_us

    def __len__(self) -> int:
        return len(self._records)

    def unique_client_ips(self) -> set[str]:
        return {r.client_ip for r in self._records}

    @property
    def coverage_start_us(self) -> int | None:
        return self._ts[0] if self._ts else None

    def candidates(self, connect_ts_us: int) -> list[HAProxyRecord]:
        lo = bisect.bisect_left(self._ts, connect_ts_us - self.window_us)
        hi = bisect.bisect_right(self._ts, connect_ts_us - self.min_delta_us)
        return self._records[lo:hi]

    def attribute(self, connect_ts: str) -> Attribution:
        connect_us = cowrie_ts_to_us(connect_ts)
        start = self.coverage_start_us
        # A connect before the first HAProxy line (the droplet shipper started
        # ~7h after the Pi's) can't be judged "missed": there was no log to miss.
        if start is None or connect_us < start:
            return Attribution(status=NO_COVERAGE)

        found = self.candidates(connect_us)
        if not found:
            return Attribution(status=MISSED)

        ips = tuple(sorted({r.client_ip for r in found}))
        if len(found) == 1 or len(ips) == 1:
            # Nearest-in-time candidate supplies the port and delta.
            best = found[-1]
            return Attribution(
                status=MATCHED if len(found) == 1 else MATCHED_SAME_IP,
                source_ip=best.client_ip,
                source_port=best.client_port,
                candidate_ips=ips,
                haproxy_ts=best.ts,
                delta_ms=round((connect_us - best.ts_us) / 1000, 3),
            )
        return Attribution(status=AMBIGUOUS, candidate_ips=ips)


def attribute_sessions(
    connect_ts_by_session: Mapping[str, str], index: HAProxyIndex
) -> dict[str, Attribution]:
    """session id -> Attribution, from each session's connect timestamp."""
    return {sid: index.attribute(ts) for sid, ts in connect_ts_by_session.items()}
