"""Read the fluent-bit archive layout: <root>/date=YYYY-MM-DD/host=<h>/*.json.gz,
each file gzip'd NDJSON, one event per line."""

from __future__ import annotations

import gzip
import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ReadStats:
    files: int = 0
    records: int = 0
    malformed: int = 0
    unreadable_files: list[str] = field(default_factory=list)


def archive_files(root: Path) -> list[Path]:
    """All *.json.gz under root, sorted so reads are deterministic."""
    return sorted(root.rglob("*.json.gz"))


def iter_records(root: Path, stats: ReadStats | None = None) -> Iterator[dict[str, Any]]:
    """Yield every JSON object in the archive. Blank lines are skipped;
    malformed lines and unreadable files are counted, never raised, so one
    truncated batch can't abort a full replay."""
    stats = stats if stats is not None else ReadStats()
    for path in archive_files(root):
        stats.files += 1
        try:
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        stats.malformed += 1
                        continue
                    if not isinstance(obj, dict):
                        stats.malformed += 1
                        continue
                    stats.records += 1
                    yield obj
        except (OSError, EOFError):
            stats.unreadable_files.append(str(path))
