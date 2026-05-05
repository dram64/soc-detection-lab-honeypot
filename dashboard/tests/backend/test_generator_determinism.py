from __future__ import annotations

import gzip
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tools.synthetic_data_generator import main, resolve_anchor


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _hash_dir(out_dir: Path) -> dict[str, str]:
    return {
        p.name: _hash_file(p)
        for p in sorted(out_dir.iterdir())
        if p.is_file() and p.suffix in (".gz", ".json")
    }


def test_explicit_anchor_is_byte_identical(tmp_path: Path) -> None:
    a = tmp_path / "run-a"
    b = tmp_path / "run-b"
    common = [
        "--events", "500",
        "--days", "1",
        "--seed", "1001",
        "--anchor-time", "2026-04-28T00:00:00Z",
    ]
    assert main([*common, "--out", str(a)]) == 0
    assert main([*common, "--out", str(b)]) == 0
    assert _hash_dir(a) == _hash_dir(b)


def test_seed_only_uses_implicit_midnight_anchor(tmp_path: Path) -> None:
    """Two same-day runs with --seed but no --anchor-time should match."""
    a = tmp_path / "run-a"
    b = tmp_path / "run-b"
    common = ["--events", "300", "--days", "1", "--seed", "7"]
    assert main([*common, "--out", str(a)]) == 0
    assert main([*common, "--out", str(b)]) == 0
    assert _hash_dir(a) == _hash_dir(b)


def test_different_seed_diverges(tmp_path: Path) -> None:
    a = tmp_path / "run-a"
    b = tmp_path / "run-b"
    anchor = ["--anchor-time", "2026-04-28T00:00:00Z"]
    assert main(["--events", "200", "--days", "1", "--seed", "1", *anchor, "--out", str(a)]) == 0
    assert main(["--events", "200", "--days", "1", "--seed", "2", *anchor, "--out", str(b)]) == 0
    assert _hash_dir(a) != _hash_dir(b)


def test_different_anchor_diverges(tmp_path: Path) -> None:
    a = tmp_path / "run-a"
    b = tmp_path / "run-b"
    seed = ["--seed", "1001"]
    assert main([
        "--events", "200", "--days", "1", *seed,
        "--anchor-time", "2026-04-28T00:00:00Z",
        "--out", str(a),
    ]) == 0
    assert main([
        "--events", "200", "--days", "1", *seed,
        "--anchor-time", "2026-04-29T00:00:00Z",
        "--out", str(b),
    ]) == 0
    # Outputs must differ; the timestamps are anchored to a different day.
    assert _hash_dir(a) != _hash_dir(b)


def test_resolve_anchor_explicit_wins() -> None:
    explicit = datetime(2026, 4, 28, 12, 0, tzinfo=timezone.utc)
    out = resolve_anchor(seed_supplied=True, anchor_time=explicit)
    assert out == explicit


def test_resolve_anchor_seed_uses_midnight_today() -> None:
    out = resolve_anchor(seed_supplied=True, anchor_time=None)
    assert out.tzinfo == timezone.utc
    assert (out.hour, out.minute, out.second, out.microsecond) == (0, 0, 0, 0)


def test_resolve_anchor_no_seed_uses_now() -> None:
    """Without --seed and without --anchor-time, fall back to wall-clock now()."""
    before = datetime.now(timezone.utc)
    out = resolve_anchor(seed_supplied=False, anchor_time=None)
    after = datetime.now(timezone.utc)
    assert before <= out <= after


def test_anchor_must_have_tzinfo(tmp_path: Path) -> None:
    """ISO 8601 without UTC offset is rejected by argparse."""
    with pytest.raises(SystemExit):
        main([
            "--events", "100", "--days", "1", "--seed", "1",
            "--anchor-time", "2026-04-28T00:00:00",  # no offset
            "--out", str(tmp_path),
        ])


def test_explicit_anchor_drives_event_timestamps(tmp_path: Path) -> None:
    """Sanity-check that timestamps in the gz output land within the
    [anchor - days, anchor + small slack] window."""
    out = tmp_path / "run"
    main([
        "--events", "200",
        "--days", "1",
        "--seed", "11",
        "--anchor-time", "2026-04-28T00:00:00Z",
        "--out", str(out),
    ])
    earliest = datetime(2026, 4, 26, 23, 59, tzinfo=timezone.utc)
    latest = datetime(2026, 4, 28, 0, 30, tzinfo=timezone.utc)
    for gz in out.glob("*.json.gz"):
        with gzip.open(gz, "rt", encoding="utf-8") as fh:
            for line in fh:
                ts = datetime.fromisoformat(json.loads(line)["timestamp"].replace("Z", "+00:00"))
                assert earliest <= ts <= latest
