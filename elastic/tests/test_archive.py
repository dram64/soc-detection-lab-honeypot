from __future__ import annotations

from pathlib import Path

from soc_elastic.archive import ReadStats, archive_files, iter_records

from .conftest import write_archive


def test_reads_all_records_in_sorted_file_order(tmp_path: Path) -> None:
    write_archive(tmp_path, "b.json.gz", [{"n": 2}])
    write_archive(tmp_path, "a.json.gz", [{"n": 1}, {"n": 1.5}])
    stats = ReadStats()
    assert [r["n"] for r in iter_records(tmp_path, stats)] == [1, 1.5, 2]
    assert (stats.files, stats.records, stats.malformed) == (2, 3, 0)
    assert [p.name for p in archive_files(tmp_path)] == ["a.json.gz", "b.json.gz"]


def test_skips_blank_counts_malformed_and_non_objects(tmp_path: Path) -> None:
    write_archive(tmp_path, "a.json.gz", [{"ok": 1}, "", "{not json", "[1, 2]"])
    stats = ReadStats()
    assert list(iter_records(tmp_path, stats)) == [{"ok": 1}]
    assert stats.malformed == 2


def test_unreadable_file_is_recorded_not_raised(tmp_path: Path) -> None:
    bad = tmp_path / "date=x" / "broken.json.gz"
    bad.parent.mkdir()
    bad.write_bytes(b"this is not gzip")
    write_archive(tmp_path, "good.json.gz", [{"ok": 1}])
    stats = ReadStats()
    assert list(iter_records(tmp_path, stats)) == [{"ok": 1}]
    assert stats.unreadable_files == [str(bad)]


def test_default_stats_object(tmp_path: Path) -> None:
    write_archive(tmp_path, "a.json.gz", [{"ok": 1}])
    assert list(iter_records(tmp_path)) == [{"ok": 1}]
