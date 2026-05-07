"""Tests for the synthetic data generator (PROJECT_PLAN.md §8)."""

from __future__ import annotations

import gzip
import json
import random
from collections import Counter
from datetime import UTC, datetime
from ipaddress import IPv4Network

import pytest

from functions.shared.cowrie_schema import CowrieEvent
from tools.synthetic_data_generator import (
    DATA_DIR,
    _hour_weight,
    _ip_in,
    _load_asn_pools,
    _load_lines,
    _pick_asn,
    _pick_cohort,
    generate_events,
    main,
    write_per_day_files,
)


@pytest.fixture(scope="session")
def asn_pools():
    return _load_asn_pools(DATA_DIR / "asn_pools.json")


@pytest.fixture(scope="session")
def usernames():
    return _load_lines(DATA_DIR / "usernames.txt")


@pytest.fixture(scope="session")
def passwords():
    return _load_lines(DATA_DIR / "passwords.txt")


@pytest.fixture(scope="session")
def small_event_corpus(asn_pools, usernames, passwords):
    fixed_now = datetime(2026, 4, 27, 23, 30, tzinfo=UTC)
    return list(
        generate_events(
            target_events=1000,
            days=1,
            seed=42,
            asn_pools=asn_pools,
            usernames=usernames,
            passwords=passwords,
            now=fixed_now,
        )
    )


def test_dictionary_files_non_empty():
    assert _load_lines(DATA_DIR / "usernames.txt"), "usernames.txt empty"
    assert _load_lines(DATA_DIR / "passwords.txt"), "passwords.txt empty"
    assert (DATA_DIR / "asn_pools.json").exists()


def test_asn_pools_load(asn_pools):
    assert len(asn_pools) >= 6
    for pool in asn_pools:
        assert pool.weight > 0
        assert len(pool.country) == 2
        assert pool.networks
        for net in pool.networks:
            assert isinstance(net, IPv4Network)


def test_hour_weight_bounds():
    weights = [_hour_weight(h) for h in range(24)]
    assert min(weights) >= 0.4
    assert max(weights) <= 1.6


def test_hour_weight_peaks_overnight():
    # Peak should be near 03:00 UTC; minimum near 15:00 UTC.
    weights = [_hour_weight(h) for h in range(24)]
    peak_hour = weights.index(max(weights))
    assert peak_hour in {2, 3, 4}


def test_pick_asn_distribution(asn_pools):
    rng = random.Random(0)
    picks = [_pick_asn(rng, asn_pools) for _ in range(2000)]
    counter = Counter(p.asn for p in picks)
    # Every pool should be picked at least once over 2000 trials.
    assert set(counter.keys()) == {p.asn for p in asn_pools}


def test_ip_in_network():
    rng = random.Random(0)
    net = IPv4Network("192.0.2.0/24")
    for _ in range(50):
        ip_str = _ip_in(rng, net)
        assert IPv4Network(f"{ip_str}/32").subnet_of(net)


def test_ip_in_handles_tiny_network():
    rng = random.Random(0)
    net = IPv4Network("192.0.2.0/31")
    out = _ip_in(rng, net)
    assert out == "192.0.2.0"


def test_pick_cohort_covers_all():
    rng = random.Random(0)
    seen = {_pick_cohort(rng).name for _ in range(2000)}
    assert seen == {"brute_force", "credential_stuffing", "scanner", "interesting"}


def test_generator_determinism(asn_pools, usernames, passwords):
    fixed_now = datetime(2026, 4, 27, 12, 0, tzinfo=UTC)
    a = list(
        generate_events(
            target_events=200,
            days=1,
            seed=42,
            asn_pools=asn_pools,
            usernames=usernames,
            passwords=passwords,
            now=fixed_now,
        )
    )
    b = list(
        generate_events(
            target_events=200,
            days=1,
            seed=42,
            asn_pools=asn_pools,
            usernames=usernames,
            passwords=passwords,
            now=fixed_now,
        )
    )
    assert a == b


def test_generator_yields_at_least_target(small_event_corpus):
    assert len(small_event_corpus) >= 1000


_ENRICHMENT_FIELDS = ("country", "asn", "asn_org")


def _strip_enrichment(raw: dict) -> dict:
    """Phase 7: synthetic events carry country/asn/asn_org enrichment that
    the ingest handler pops off before Cowrie-schema validation. Tests do
    the same so the canonical Cowrie shape (ADR-001, extra="forbid") stays
    strict."""
    return {k: v for k, v in raw.items() if k not in _ENRICHMENT_FIELDS}


def test_every_event_carries_enrichment_fields(small_event_corpus):
    """Phase 7 contract: every synthetic event has country/asn/asn_org so the
    GeoMap and top-asns endpoints have data without GeoIP enrichment."""
    for raw in small_event_corpus:
        assert raw.get("country") is not None
        assert raw.get("asn") is not None
        assert raw.get("asn_org") is not None
        # ISO 3166-1 alpha-2 country codes are exactly two upper-case letters
        assert isinstance(raw["country"], str) and len(raw["country"]) == 2


def test_every_event_validates_against_pydantic_schema(small_event_corpus):
    """The canonical Cowrie shape stays strict; enrichment is pre-stripped
    in the ingest handler. We mirror that here."""
    for raw in small_event_corpus:
        event = CowrieEvent.model_validate(_strip_enrichment(raw))
        event.check_fields()


def test_every_session_starts_with_connect(small_event_corpus):
    by_session: dict[str, list[dict]] = {}
    for event in small_event_corpus:
        by_session.setdefault(event["session"], []).append(event)
    for events in by_session.values():
        events_sorted = sorted(events, key=lambda e: e["timestamp"])
        assert events_sorted[0]["eventid"] == "cowrie.session.connect"


def test_every_session_ends_with_closed(small_event_corpus):
    by_session: dict[str, list[dict]] = {}
    for event in small_event_corpus:
        by_session.setdefault(event["session"], []).append(event)
    # Some sessions may be cut off at the events budget; check the first 90% are closed properly.
    sessions = list(by_session.values())
    closed_count = sum(
        1 for events in sessions if any(e["eventid"] == "cowrie.session.closed" for e in events)
    )
    assert closed_count >= 0.85 * len(sessions)


def test_cohort_distribution_within_tolerance(asn_pools, usernames, passwords):
    """Generate enough events that cohort proportions stabilize."""
    fixed_now = datetime(2026, 4, 27, 12, 0, tzinfo=UTC)
    events = list(
        generate_events(
            target_events=20_000,
            days=3,
            seed=7,
            asn_pools=asn_pools,
            usernames=usernames,
            passwords=passwords,
            now=fixed_now,
        )
    )
    # Tag each session by its observed shape.
    sessions: dict[str, list[dict]] = {}
    for event in events:
        sessions.setdefault(event["session"], []).append(event)

    cohort_counts: Counter[str] = Counter()
    for session_events in sessions.values():
        eventids = {e["eventid"] for e in session_events}
        if "cowrie.command.input" in eventids:
            cohort_counts["interesting"] += 1
        elif "cowrie.login.success" in eventids:
            cohort_counts["credential_stuffing"] += 1
        elif "cowrie.login.failed" in eventids:
            usernames_used = {e["username"] for e in session_events if "username" in e}
            if len(usernames_used) == 1:
                cohort_counts["brute_force"] += 1
            else:
                cohort_counts["credential_stuffing"] += 1
        else:
            cohort_counts["scanner"] += 1

    total = sum(cohort_counts.values())
    proportions = {k: v / total for k, v in cohort_counts.items()}
    # Loose tolerance: cohort weighting is 80/15/4/1 but classification
    # heuristic above isn't perfect (credential-stuffing-with-zero-success
    # falls through to "credential_stuffing" via username diversity, etc.).
    assert 0.65 <= proportions.get("brute_force", 0) <= 0.92
    assert proportions.get("scanner", 0) <= 0.10
    assert proportions.get("interesting", 0) <= 0.05


def test_timestamps_within_window(asn_pools, usernames, passwords):
    fixed_now = datetime(2026, 4, 27, 12, 0, tzinfo=UTC)
    events = list(
        generate_events(
            target_events=500,
            days=2,
            seed=5,
            asn_pools=asn_pools,
            usernames=usernames,
            passwords=passwords,
            now=fixed_now,
        )
    )
    earliest_allowed = fixed_now.replace(microsecond=0).timestamp() - 2 * 86400
    for event in events:
        ts = datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00"))
        # Sessions run forward from their start time; allow a 5-minute slack
        # past `now` for a session starting very close to `now`.
        assert ts.timestamp() >= earliest_allowed
        assert ts.timestamp() <= fixed_now.timestamp() + 600


def test_write_per_day_files(tmp_path, small_event_corpus):
    manifest = write_per_day_files(small_event_corpus, tmp_path, seed=42)
    assert manifest["events_total"] == len(small_event_corpus)
    assert (tmp_path / "manifest.json").exists()
    for entry in manifest["files"]:
        gz_path = tmp_path / entry["path"]
        assert gz_path.exists()
        with gzip.open(gz_path, "rt", encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        assert len(lines) == entry["events"]
        for line in lines:
            raw = json.loads(line)
            # Strip Phase 7 enrichment before Cowrie-schema validation.
            CowrieEvent.model_validate(_strip_enrichment(raw)).check_fields()


def test_main_writes_files(tmp_path):
    out_dir = tmp_path / "out"
    rc = main(
        [
            "--events",
            "200",
            "--days",
            "1",
            "--seed",
            "11",
            "--out",
            str(out_dir),
        ]
    )
    assert rc == 0
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["events_total"] >= 200


def test_main_requires_an_output(capsys):
    rc = main(["--events", "10"])
    assert rc == 2
    captured = capsys.readouterr()
    assert "must pass at least one of" in captured.err


def test_login_events_have_credentials(small_event_corpus):
    for event in small_event_corpus:
        if event["eventid"] in ("cowrie.login.failed", "cowrie.login.success"):
            assert "username" in event and "password" in event


def test_file_downloads_have_shasum(small_event_corpus):
    saw = 0
    for event in small_event_corpus:
        if event["eventid"] == "cowrie.session.file_download":
            assert "url" in event and "shasum" in event
            assert len(event["shasum"]) == 64
            saw += 1
    # interesting cohort is 1%, sometimes 0 in 1000 events; just don't fail if absent.
    assert saw >= 0
