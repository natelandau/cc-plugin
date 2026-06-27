"""Verify frontmatter extraction reads only the header and lists learnings."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path
    from types import ModuleType


def _write(p: Path, summary: str, read_when: str, body: str = "body") -> None:
    p.write_text(
        f"---\nsummary: {summary}\nread_when: {read_when}\n---\n{body}\n", encoding="utf-8"
    )


def test_extract_inline_list(tmp_path: Path, load_recall_module: Callable[..., ModuleType]) -> None:
    """Verify summary and an inline read_when list parse."""
    # Given a learning file with an inline read_when list
    frontmatter = load_recall_module("lib", "frontmatter.py")
    f = tmp_path / "a.md"
    _write(f, "Avoid the X trap", '["touching X", "debugging Y"]')
    # When extracted
    summary, read_when = frontmatter.extract_frontmatter(f)
    # Then both fields come back
    assert summary == "Avoid the X trap"
    assert read_when == ["touching X", "debugging Y"]


def test_extract_missing_frontmatter(
    tmp_path: Path, load_recall_module: Callable[..., ModuleType]
) -> None:
    """Verify a file without frontmatter yields empties."""
    # Given a file with no frontmatter
    frontmatter = load_recall_module("lib", "frontmatter.py")
    f = tmp_path / "b.md"
    f.write_text("just text\n", encoding="utf-8")
    # When extracted
    summary, read_when = frontmatter.extract_frontmatter(f)
    # Then both are empty
    assert summary == ""
    assert read_when == []


def test_scan_learnings_sorted_and_filtered(
    tmp_path: Path, load_recall_module: Callable[..., ModuleType]
) -> None:
    """Verify scan returns only files with a summary, sorted by path."""
    # Given two valid learnings and one without a summary
    frontmatter = load_recall_module("lib", "frontmatter.py")
    _write(tmp_path / "two.md", "second", "[]")
    _write(tmp_path / "one.md", "first", "[]")
    (tmp_path / "skip.md").write_text("no frontmatter\n", encoding="utf-8")
    # When scanning the directory
    out = frontmatter.scan_learnings(tmp_path)
    # Then only summarized files appear, sorted by filename
    assert [p.name for p, _, _ in out] == ["one.md", "two.md"]


def test_scan_missing_dir(tmp_path: Path, load_recall_module: Callable[..., ModuleType]) -> None:
    """Verify scanning a nonexistent dir yields an empty list."""
    # Given a directory that does not exist
    frontmatter = load_recall_module("lib", "frontmatter.py")
    # When scanned
    out = frontmatter.scan_learnings(tmp_path / "nope")
    # Then the result is empty
    assert out == []
