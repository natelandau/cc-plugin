"""Verify frontmatter extraction reads only the header and lists learnings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from recall.frontmatter import extract, scan_learnings  # ty: ignore[unresolved-import]

if TYPE_CHECKING:
    from pathlib import Path


def _write(p: Path, summary: str, read_when: str, body: str = "body") -> None:
    p.write_text(
        f"---\nsummary: {summary}\nread_when: {read_when}\n---\n{body}\n", encoding="utf-8"
    )


def test_extract_inline_list(tmp_path: Path) -> None:
    """Verify summary and an inline read_when list parse."""
    # Given a learning file with an inline read_when list
    f = tmp_path / "a.md"
    _write(f, "Avoid the X trap", '["touching X", "debugging Y"]')
    # When extracted
    summary, read_when = extract(f)
    # Then both fields come back
    assert summary == "Avoid the X trap"
    assert read_when == ["touching X", "debugging Y"]


def test_extract_block_list(tmp_path: Path) -> None:
    """Verify a YAML block-style read_when list parses."""
    # Given a learning file with a block list
    f = tmp_path / "a.md"
    f.write_text(
        "---\nsummary: Block list\nread_when:\n  - touching A\n  - touching B\n---\nbody\n",
        encoding="utf-8",
    )
    # When extracted
    summary, read_when = extract(f)
    # Then the block items are collected
    assert summary == "Block list"
    assert read_when == ["touching A", "touching B"]


def test_extract_missing_frontmatter(tmp_path: Path) -> None:
    """Verify a file without frontmatter yields empties."""
    # Given a file with no frontmatter
    f = tmp_path / "b.md"
    f.write_text("just text\n", encoding="utf-8")
    # When extracted
    summary, read_when = extract(f)
    # Then both are empty
    assert summary == ""
    assert read_when == []


def test_scan_learnings_sorted_and_filtered(tmp_path: Path) -> None:
    """Verify scan returns only files with a summary, sorted by path."""
    # Given two valid learnings and one without a summary
    _write(tmp_path / "two.md", "second", "[]")
    _write(tmp_path / "one.md", "first", "[]")
    (tmp_path / "skip.md").write_text("no frontmatter\n", encoding="utf-8")
    # When scanning the directory
    out = scan_learnings(tmp_path)
    # Then only summarized files appear, sorted by filename
    assert [p.name for p, _, _ in out] == ["one.md", "two.md"]


def test_scan_missing_dir(tmp_path: Path) -> None:
    """Verify scanning a nonexistent dir yields an empty list."""
    # Given a directory that does not exist / When scanned
    out = scan_learnings(tmp_path / "nope")
    # Then the result is empty
    assert out == []
