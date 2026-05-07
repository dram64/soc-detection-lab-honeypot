r"""Strip phase-tagged comments and meta-narrative from source files.

Removes:
  1. Top-of-file /** ... */ JSDoc blocks (.ts/.tsx/.js/.jsx) if they
     contain phase tokens -- the FIRST block in the file only.
  2. Top-of-file Python module docstrings if they contain phase tokens.
     Function and class docstrings are NEVER touched.
  3. Top-of-file Terraform comment headers (lines starting with `#`)
     when the FIRST contiguous comment block contains phase tokens.
  4. Whole-line comments matching the phase-token patterns.
  5. Inline phase parentheticals like "(Phase 6.1)" / "; see ADR 015".
  6. Phase token prefixes like "Phase 8.5: " / "Phase 5L cron".

Hard rules (designed against the user's prior burn):
  * No regex matches `()` or any bare-parens construct.
  * No global whitespace-collapse.
  * Single-file mode by default; --apply needed to actually write.
  * Per-file in-memory diff is printed in --dry-run.

Phase tokens are matched as a closed vocabulary:
  Phase \d, PHASE_\d, Track \d, Bug \d, PART \d, Treatment [A-Z],
  ADR-\d{3} / ADR \d{3}, design-preview, post-park, capstone-narrative.

Usage:
  python humanize_comments.py --dry-run path/to/file.py
  python humanize_comments.py --dry-run path/to/dir/  (recursive)
  python humanize_comments.py --apply path/to/file.py
"""

from __future__ import annotations

import argparse
import contextlib
import difflib
import re
import sys
from pathlib import Path

# Match these tokens. Phase tokens use word boundaries on both sides
# where possible to avoid overreach. ADR variants accept hyphen or space.
PHASE_TOKEN_RE = re.compile(
    r"\b(?:"
    r"Phase\s*\d+(?:\.\d+)?[A-Za-z]?"  # Phase 8, Phase 8.5, Phase 5L
    r"|PHASE_\d+(?:_\d+)?"  # PHASE_8, PHASE_8_5
    r"|Track\s*\d+"
    r"|Bug\s*\d+"
    r"|PART\s*\d+"
    r"|Treatment\s+[A-Z]"
    r"|ADR[-\s]?\d{3}"  # ADR-005, ADR 005
    r"|design-preview"
    r"|post-park"
    r"|capstone-narrative"
    r")\b",
    flags=re.IGNORECASE,
)

# Inline parentheticals like "(Phase 6.1)", "(was a player matchup in Phase 6)",
# "(Phase 6 commit a9f2c46)". Conservative: must START with "(Phase " /
# "(ADR " etc. — never matches arbitrary parens.
INLINE_PARENTHETICAL_RE = re.compile(
    r"\s*\((?:Phase|PHASE_|Track|Bug|PART|Treatment|ADR[-\s]?\d|design-preview|post-park)\b[^)]*\)"
)

# Trailing phase asides preceded by ; or — like "; see ADR 015" or
# "— Phase 8.5 amendment". Conservative: must consume the leading
# punctuation + whitespace.
# Regex character class intentionally matches em-dash and en-dash chars
# alongside semicolon and hyphen; this script's purpose is to normalize
# those chars in comments. Replacing them defeats the matching.
TRAILING_ASIDE_RE = re.compile(
    r"\s*[;—–\-]+\s*(?:see\s+)?(?:Phase|PHASE_|Track|Bug|PART|Treatment|ADR[-\s]?\d|design-preview|post-park)\b[^.\n]*"  # noqa: RUF001
)

# Phase prefixes that are siblings of other text. Match "Phase 8.5: " or
# "Phase 8.5 — " at the start of a comment body (after the comment marker).
# Char class matches em-dash + en-dash deliberately; same rationale as
# TRAILING_ASIDE_RE above.
PHASE_PREFIX_RE = re.compile(
    r"^(\s*(?://|#|--)\s*)(?:Phase\s*\d+(?:\.\d+)?[A-Za-z]?|PHASE_\d+(?:_\d+)?|Track\s*\d+|Bug\s*\d+|PART\s*\d+|Treatment\s+[A-Z])\s*[:—–\-]\s*",  # noqa: RUF001
    flags=re.IGNORECASE,
)


def _strip_top_jsdoc_block(text: str) -> tuple[str, bool]:
    """Strip the FIRST /** ... */ block in text iff it (a) starts within
    the first 5 non-blank lines and (b) contains a phase token.
    Returns (new_text, changed)."""
    # Find first `/**` ignoring leading whitespace + blank lines.
    m = re.match(r"^\s*/\*\*", text)
    if not m:
        return text, False
    end = text.find("*/", m.end())
    if end == -1:
        return text, False
    block = text[: end + 2]
    if not PHASE_TOKEN_RE.search(block):
        return text, False
    # Strip the block + the immediately following blank line if present.
    rest = text[end + 2 :]
    if rest.startswith("\n"):
        rest = rest[1:]
    return rest, True


def _strip_top_py_docstring(text: str) -> tuple[str, bool]:
    """Strip the FIRST module-level docstring iff it contains a phase token.
    Function/class docstrings are NEVER touched.
    Module docstring = first triple-quoted block before any non-comment,
    non-blank Python statement.
    """
    # Skip leading blank lines + shebang + encoding decl.
    lines = text.splitlines(keepends=True)
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if not s or s.startswith("#"):
            i += 1
            continue
        break
    if i >= len(lines):
        return text, False
    s = lines[i].lstrip()
    if not (s.startswith('"""') or s.startswith("'''")):
        return text, False
    quote = '"""' if s.startswith('"""') else "'''"
    # Single-line docstring on this line?
    line_after_quote = s[3:]
    if line_after_quote.rstrip().endswith(quote) and len(line_after_quote.rstrip()) >= 3:
        block = lines[i]
        if not PHASE_TOKEN_RE.search(block):
            return text, False
        new_lines = lines[:i] + lines[i + 1 :]
        # Also drop the blank line that often follows.
        if i < len(new_lines) and new_lines[i].strip() == "":
            new_lines.pop(i)
        return "".join(new_lines), True
    # Multi-line docstring.
    end_idx = None
    for j in range(i + 1, len(lines)):
        if quote in lines[j]:
            end_idx = j
            break
    if end_idx is None:
        return text, False
    block = "".join(lines[i : end_idx + 1])
    if not PHASE_TOKEN_RE.search(block):
        return text, False
    new_lines = lines[:i] + lines[end_idx + 1 :]
    if i < len(new_lines) and new_lines[i].strip() == "":
        new_lines.pop(i)
    return "".join(new_lines), True


def _strip_top_tf_header(text: str) -> tuple[str, bool]:
    """Strip the FIRST contiguous block of `#`-comment lines at the top of
    a Terraform file iff it contains a phase token.
    """
    lines = text.splitlines(keepends=True)
    i = 0
    # Skip leading blank lines.
    while i < len(lines) and lines[i].strip() == "":
        i += 1
    start = i
    while i < len(lines) and lines[i].lstrip().startswith("#"):
        i += 1
    if i == start:
        return text, False
    block = "".join(lines[start:i])
    if not PHASE_TOKEN_RE.search(block):
        return text, False
    new_lines = lines[:start] + lines[i:]
    if start < len(new_lines) and new_lines[start].strip() == "":
        new_lines.pop(start)
    return "".join(new_lines), True


def _strip_phase_only_comment_lines(text: str, marker: str) -> tuple[str, int]:
    """Drop whole lines that are JUST a phase-tagged comment.
    `marker` is // or # or --. The line must have only whitespace +
    the marker + a body matching a phase token, with no other content.
    """
    pat = re.compile(
        r"^\s*"
        + re.escape(marker)
        + r"\s*(?:Phase|PHASE_|Track|Bug|PART|Treatment|ADR[-\s]?\d|design-preview|post-park|capstone-narrative)\b[^\n]*\n",
        flags=re.MULTILINE | re.IGNORECASE,
    )
    new_text, n = pat.subn("", text)
    return new_text, n


def _strip_inline_phase_parentheticals(text: str, marker: str) -> tuple[str, int]:
    """Strip "(Phase 6.1)" and friends ONLY when they appear inside a
    line that has a comment marker -- never touches code-side text.

    Post-pass: clean up the orphan period that appears when the
    parenthetical was the only content between marker and a sentence end:
        before: "# (Phase X). The rest"  -> after strip: "#. The rest"
                                         -> cleanup:    "# The rest"
    """
    # Match the orphan-period shape: marker, optional whitespace, a single
    # period, then a space and the next sentence. Replace with marker + space.
    orphan_pat = re.compile(r"^(\s*" + re.escape(marker) + r")\s*\.\s+", flags=re.MULTILINE)

    out_lines = []
    n = 0
    for line in text.splitlines(keepends=True):
        if marker in line:
            new_line, k = INLINE_PARENTHETICAL_RE.subn("", line)
            n += k
            if k:
                new_line = orphan_pat.sub(r"\1 ", new_line, count=1)
            out_lines.append(new_line)
        else:
            out_lines.append(line)
    return "".join(out_lines), n


def _strip_trailing_asides(text: str, marker: str) -> tuple[str, int]:
    """Strip "; see ADR 015" / "— Phase 8 amendment" trailing asides
    ONLY inside comment lines.
    """
    out_lines = []
    n = 0
    for line in text.splitlines(keepends=True):
        idx = line.find(marker)
        if idx == -1:
            out_lines.append(line)
            continue
        # Operate only on the comment portion (after the marker).
        prefix = line[:idx]
        rest = line[idx:]
        # Preserve trailing newline.
        nl = ""
        if rest.endswith("\n"):
            nl = "\n"
            rest = rest[:-1]
        new_rest, k = TRAILING_ASIDE_RE.subn("", rest)
        n += k
        out_lines.append(prefix + new_rest + nl)
    return "".join(out_lines), n


def _strip_phase_prefix_in_comments(text: str) -> tuple[str, int]:
    """Strip "Phase 8.5: " prefix at the start of comment bodies, leaving
    the rest of the comment intact. Operates per-line.
    """
    pat = PHASE_PREFIX_RE
    out_lines = []
    n = 0
    for line in text.splitlines(keepends=True):
        m = pat.match(line)
        if m:
            new_line = pat.sub(r"\1", line, count=1)
            if new_line != line:
                n += 1
                out_lines.append(new_line)
                continue
        out_lines.append(line)
    return "".join(out_lines), n


COMMENT_MARKERS_BY_EXT: dict[str, str] = {
    ".py": "#",
    ".ts": "//",
    ".tsx": "//",
    ".js": "//",
    ".jsx": "//",
    ".tf": "#",
    ".html": "//",  # we don't actually strip HTML comments here — see process_text
    ".css": "//",
}


def process_text(text: str, ext: str) -> tuple[str, dict]:
    """Run the full sweep on a single file's text. Returns (new_text, stats)."""
    stats = {
        "top_jsdoc": 0,
        "top_pydocstring": 0,
        "top_tf_header": 0,
        "phase_only_lines": 0,
        "inline_parentheticals": 0,
        "trailing_asides": 0,
        "phase_prefixes": 0,
    }
    out = text

    if ext in {".ts", ".tsx", ".js", ".jsx"}:
        out, did = _strip_top_jsdoc_block(out)
        stats["top_jsdoc"] = int(did)
        marker = "//"
    elif ext == ".py":
        out, did = _strip_top_py_docstring(out)
        stats["top_pydocstring"] = int(did)
        marker = "#"
    elif ext == ".tf":
        out, did = _strip_top_tf_header(out)
        stats["top_tf_header"] = int(did)
        marker = "#"
    else:
        marker = None

    if marker is not None:
        out, n = _strip_phase_only_comment_lines(out, marker)
        stats["phase_only_lines"] = n
        out, n = _strip_inline_phase_parentheticals(out, marker)
        stats["inline_parentheticals"] = n
        out, n = _strip_trailing_asides(out, marker)
        stats["trailing_asides"] = n
        out, n = _strip_phase_prefix_in_comments(out)
        stats["phase_prefixes"] = n

    return out, stats


def _iter_files(paths: list[Path], includes: set[str]) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        if p.is_file():
            if p.suffix in includes:
                out.append(p)
        elif p.is_dir():
            for f in p.rglob("*"):
                if not f.is_file():
                    continue
                if f.suffix not in includes:
                    continue
                # Hard-exclude rules
                parts = f.parts
                if any(
                    seg
                    in {
                        "node_modules",
                        ".venv",
                        ".terraform",
                        "dist",
                        "build",
                        "__pycache__",
                        ".git",
                        "coverage",
                        "frontend-apex",
                    }
                    for seg in parts
                ):
                    continue
                # Skip generated package-lock.json etc.
                if f.name == "package-lock.json":
                    continue
                # Skip phase log markdown — narrative by genre.
                if f.name.startswith("PHASE_") and f.suffix == ".md":
                    continue
                out.append(f)
    return out


def main() -> int:
    # Windows default stdout codec is cp1252; diffs may contain unicode (→ etc.)
    with contextlib.suppress(Exception):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    parser.add_argument("--dry-run", action="store_true", help="print diffs (default)")
    parser.add_argument(
        "--ext", default=".py,.ts,.tsx,.js,.jsx,.tf", help="comma-separated extensions to include"
    )
    args = parser.parse_args()

    apply = args.apply and not args.dry_run
    includes = {e.strip() for e in args.ext.split(",") if e.strip()}

    files = _iter_files(args.paths, includes)
    total_stats = {
        "files_scanned": 0,
        "files_changed": 0,
        "top_jsdoc": 0,
        "top_pydocstring": 0,
        "top_tf_header": 0,
        "phase_only_lines": 0,
        "inline_parentheticals": 0,
        "trailing_asides": 0,
        "phase_prefixes": 0,
    }

    for f in files:
        total_stats["files_scanned"] += 1
        try:
            orig = f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        new, stats = process_text(orig, f.suffix)
        if new == orig:
            continue
        total_stats["files_changed"] += 1
        for k, v in stats.items():
            total_stats[k] += v
        if apply:
            f.write_text(new, encoding="utf-8")
        else:
            diff = difflib.unified_diff(
                orig.splitlines(keepends=True),
                new.splitlines(keepends=True),
                fromfile=str(f),
                tofile=str(f),
                n=2,
            )
            sys.stdout.writelines(diff)
            sys.stdout.write("\n")

    print("---")
    for k, v in total_stats.items():
        print(f"  {k}: {v}")
    print("(dry-run)" if not apply else "(applied)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
