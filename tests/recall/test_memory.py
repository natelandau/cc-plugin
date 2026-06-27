"""Verify the injected memory blocks: architecture cap, index, backlog summary."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path
    from types import ModuleType

# Directory name constants mirrored here to avoid module-level lib import
_LEARNINGS_DIRNAME = "learnings"
_ARCHITECTURE_NAME = "architecture.md"
_BACKLOG_NAME = "backlog.md"


def _seed(data: Path) -> None:
    (data / _LEARNINGS_DIRNAME).mkdir(parents=True)
    (data / _LEARNINGS_DIRNAME / "x.md").write_text(
        '---\nsummary: The X gotcha\nread_when: ["touching X"]\n---\nbody\n',
        encoding="utf-8",
    )
    (data / _ARCHITECTURE_NAME).write_text("# Goals\nKeep it small.\n", encoding="utf-8")
    (data / _BACKLOG_NAME).write_text(
        "## fix\n- [ ] [S] tiny thing — 2026-06-26\n- [ ] [L] big thing — 2026-06-26\n"
        "## feat\n- [ ] [M] feature — 2026-06-26\n",
        encoding="utf-8",
    )


def test_architecture_under_cap_is_whole(
    tmp_path: Path, import_recall_module: Callable[[str], ModuleType]
) -> None:
    """Verify architecture.md within the cap is injected verbatim."""
    # Given a small architecture file
    _seed(tmp_path)
    memory = import_recall_module("lib.memory")
    # When building the block with a generous cap
    out = memory.architecture_block(tmp_path, max_bytes=10_000)
    # Then the whole file content appears, no truncation marker
    assert "Keep it small." in out
    assert "truncated" not in out


def test_architecture_over_cap_truncates_with_note(
    tmp_path: Path, import_recall_module: Callable[[str], ModuleType]
) -> None:
    """Verify an oversized architecture.md is capped with an explicit note."""
    # Given an architecture file larger than the cap
    _seed(tmp_path)
    (tmp_path / _ARCHITECTURE_NAME).write_text("A" * 5000, encoding="utf-8")
    memory = import_recall_module("lib.memory")
    # When building with a small cap
    out = memory.architecture_block(tmp_path, max_bytes=100)
    # Then content is bounded and a truncation marker is present (no silent loss)
    assert "truncated" in out.lower()
    assert len(out) < 1000


def test_learnings_index_lists_summary_and_hint(
    tmp_path: Path, import_recall_module: Callable[[str], ModuleType]
) -> None:
    """Verify the index shows the summary and the read-when hint, not the body."""
    # Given a seeded store
    _seed(tmp_path)
    memory = import_recall_module("lib.memory")
    # When building the index
    out = memory.learnings_index(tmp_path)
    # Then the summary and hint appear and the body does not
    assert "The X gotcha" in out
    assert "touching X" in out
    assert "body" not in out


def test_backlog_summary_counts_and_quick_wins(
    tmp_path: Path, import_recall_module: Callable[[str], ModuleType]
) -> None:
    """Verify the backlog summary counts per type and surfaces [S] quick-wins."""
    # Given a seeded backlog with fix/feat sections
    _seed(tmp_path)
    memory = import_recall_module("lib.memory")
    # When summarizing
    out = memory.backlog_summary(tmp_path)
    # Then totals, per-type counts, and the [S] item are present; [L]/[M] are not inlined
    assert "3 deferred" in out
    assert "2 fix" in out
    assert "1 feat" in out
    assert "tiny thing" in out
    assert "big thing" not in out


def test_empty_store_injects_nothing(
    tmp_path: Path, import_recall_module: Callable[[str], ModuleType]
) -> None:
    """Verify an empty store yields an empty injection."""
    # Given an empty data dir
    memory = import_recall_module("lib.memory")
    # When building the full injection
    out = memory.build_injection(tmp_path, architecture_max_bytes=4096)
    # Then nothing is injected
    assert out == ""
