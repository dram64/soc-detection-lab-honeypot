from __future__ import annotations

from soc_elastic.correlate import (
    AMBIGUOUS,
    MATCHED,
    MATCHED_SAME_IP,
    MISSED,
    NO_CONNECT,
    NO_COVERAGE,
    UNATTRIBUTED_NO_CONNECT,
    HAProxyIndex,
    attribute_sessions,
)

from .conftest import hp

CONNECT = "2026-05-10T12:00:01.000000Z"


def test_single_candidate_in_window_is_matched_with_port_and_delta() -> None:
    idx = HAProxyIndex([hp("2026-05-10T12:00:00.750000Z", "203.0.113.5", 51000)])
    a = idx.attribute(CONNECT)
    assert a.status == MATCHED and a.attributed
    assert (a.source_ip, a.source_port) == ("203.0.113.5", 51000)
    assert a.delta_ms == 250.0
    assert a.haproxy_ts == "2026-05-10T12:00:00.750000+00:00"


def test_window_bounds_are_inclusive_500ms_and_1ms_floor() -> None:
    at_500 = HAProxyIndex([hp("2026-05-10T12:00:00.500000Z", "203.0.113.1")])
    at_1 = HAProxyIndex([hp("2026-05-10T12:00:00.999000Z", "203.0.113.1")])
    assert at_500.attribute(CONNECT).status == MATCHED
    assert at_1.attribute(CONNECT).status == MATCHED


def test_outside_window_or_inside_floor_is_missed() -> None:
    too_old = hp("2026-05-10T12:00:00.499999Z", "203.0.113.1")
    too_close = hp("2026-05-10T12:00:00.999500Z", "203.0.113.2")  # 0.5 ms before
    after = hp("2026-05-10T12:00:01.100000Z", "203.0.113.3")
    idx = HAProxyIndex([too_old, too_close, after])
    a = idx.attribute(CONNECT)
    assert a.status == MISSED and not a.attributed and a.source_ip is None


def test_multiple_candidates_same_ip_attributes_to_nearest() -> None:
    idx = HAProxyIndex(
        [
            hp("2026-05-10T12:00:00.600000Z", "198.51.100.7", 1111),
            hp("2026-05-10T12:00:00.900000Z", "198.51.100.7", 2222),
        ]
    )
    a = idx.attribute(CONNECT)
    assert a.status == MATCHED_SAME_IP and a.attributed
    assert (a.source_ip, a.source_port, a.delta_ms) == ("198.51.100.7", 2222, 100.0)


def test_multiple_candidates_different_ips_is_ambiguous_and_unattributed() -> None:
    idx = HAProxyIndex(
        [
            hp("2026-05-10T12:00:00.600000Z", "198.51.100.9"),
            hp("2026-05-10T12:00:00.900000Z", "198.51.100.7"),
        ]
    )
    a = idx.attribute(CONNECT)
    assert a.status == AMBIGUOUS and not a.attributed and a.source_ip is None
    assert a.candidate_ips == ("198.51.100.7", "198.51.100.9")


def test_connect_before_haproxy_coverage_is_not_counted_as_missed() -> None:
    idx = HAProxyIndex([hp("2026-05-10T13:00:00.000000Z", "203.0.113.5")])
    assert idx.attribute(CONNECT).status == NO_COVERAGE
    assert HAProxyIndex([]).attribute(CONNECT).status == NO_COVERAGE


def test_index_sorts_input_and_reports_ips() -> None:
    idx = HAProxyIndex(
        [hp("2026-05-10T12:00:00.900000Z", "b"), hp("2026-05-10T11:00:00.000000Z", "a")]
    )
    assert len(idx) == 2
    assert idx.unique_client_ips() == {"a", "b"}
    assert idx.coverage_start_us is not None


def test_attribute_sessions_maps_each_session() -> None:
    idx = HAProxyIndex([hp("2026-05-10T12:00:00.750000Z", "203.0.113.5")])
    out = attribute_sessions({"s1": CONNECT, "s2": "2026-05-10T15:00:00.000000Z"}, idx)
    assert out["s1"].status == MATCHED and out["s2"].status == MISSED
    assert UNATTRIBUTED_NO_CONNECT.status == NO_CONNECT
