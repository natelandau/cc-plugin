"""Read `summary` + `read_when` from a learning file's YAML frontmatter.

Only the header block is read, never the body, so building the always-injected
learnings index from N files costs N small reads. The index is a view over the
files (no separate index.md to drift). See spec §4.3, §5.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def _read_header(path: Path) -> list[str] | None:
    """Read lines between the opening and closing `---` fences.

    Returns `None` when the file has no valid frontmatter block so the caller
    can fail open without raising.

    Args:
        path: Path to the markdown file to read.

    Returns:
        List of raw header lines, or None if no valid frontmatter found.
    """
    try:
        with path.open(encoding="utf-8") as fh:
            if not fh.readline().startswith("---"):
                return None
            header_lines: list[str] = []
            for line in fh:
                if line.strip() == "---":
                    return header_lines
                header_lines.append(line.rstrip("\n"))
    except OSError:
        return None
    return None  # closing --- was never reached


def _parse_inline_list(value: str) -> list[str]:
    """Parse an inline JSON-ish list string into a flat Python list.

    Accepts both double- and single-quoted elements. Returns an empty list
    when the value is not a bracketed list or is malformed JSON.

    Args:
        value: The raw string value after `read_when:`.

    Returns:
        Parsed list of non-empty strings, or an empty list on failure.
    """
    if not (value.startswith("[") and value.endswith("]")):
        return []
    try:
        parsed = json.loads(value.replace("'", '"'))
    except json.JSONDecodeError, ValueError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(x).strip() for x in parsed if str(x).strip()]


def extract_frontmatter(path: Path) -> tuple[str, list[str]]:
    """Return `(summary, read_when)` from a file's frontmatter, empties if absent.

    Reads up to the closing `---` only. `read_when` accepts an inline JSON-ish
    list (`["a", "b"]`) or a YAML block list of `- item` lines. Any read error
    yields `("", [])` so the caller fails open.

    Args:
        path: Path to the markdown learning file to parse.

    Returns:
        A tuple of (summary string, read_when list); both empty if no valid frontmatter.
    """
    header_lines = _read_header(path)
    if header_lines is None:
        return "", []

    summary = ""
    read_when: list[str] = []
    collecting = False
    for line in header_lines:
        stripped = line.strip()
        if stripped.startswith("summary:"):
            summary = stripped[len("summary:") :].strip().strip("'\"")
            collecting = False
        elif stripped.startswith("read_when:"):
            collecting = True
            read_when = _parse_inline_list(stripped[len("read_when:") :].strip())
        elif collecting and stripped.startswith("- "):
            hint = stripped[2:].strip().strip("'\"")
            if hint:
                read_when.append(hint)
        elif collecting and stripped:
            collecting = False
    return summary, read_when


def scan_learnings(learnings_dir: Path) -> list[tuple[Path, str, list[str]]]:
    """Return `(file, summary, read_when)` for each summarized `*.md`, sorted.

    Files lacking a `summary` are skipped (a learning with no index line is not
    surfaced). A missing directory yields an empty list.

    Args:
        learnings_dir: Directory to scan for `*.md` learning files.

    Returns:
        Sorted list of (path, summary, read_when) tuples for files that have a summary.
    """
    if not learnings_dir.is_dir():
        return []
    out: list[tuple[Path, str, list[str]]] = []
    for md in sorted(learnings_dir.glob("*.md")):
        summary, read_when = extract_frontmatter(md)
        if summary:
            out.append((md, summary, read_when))
    return out
