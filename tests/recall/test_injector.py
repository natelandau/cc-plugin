"""Verify the SessionStart injector: learnings index and backlog summary."""

from __future__ import annotations

from typing import TYPE_CHECKING

from recall.config import RecallConfig  # ty: ignore[unresolved-import]
from recall.injector import Injector  # ty: ignore[unresolved-import]
from recall.store import Store  # ty: ignore[unresolved-import]

if TYPE_CHECKING:
    from pathlib import Path


def _store(tmp_path: Path) -> Store:
    return Store(key="k", data_dir=tmp_path / "data", state_dir=tmp_path / "state")


def _seed(store: Store) -> None:
    """Seed a store with one learning and a mixed backlog."""
    store.learnings_dir.mkdir(parents=True)
    (store.learnings_dir / "x.md").write_text(
        '---\nsummary: The X gotcha\nread_when: ["touching X"]\n---\nbody\n', encoding="utf-8"
    )
    store.backlog_path.write_text(
        "## fix\n- [ ] [S] tiny thing — 2026-06-26\n- [ ] [L] big thing — 2026-06-26\n"
        "## feat\n- [ ] [M] feature — 2026-06-26\n",
        encoding="utf-8",
    )


def test_build_empty_store_returns_blank(tmp_path: Path) -> None:
    """Verify an empty store injects nothing."""
    # Given an empty store / When building the injection
    out = Injector(_store(tmp_path), RecallConfig()).build()
    # Then nothing is injected
    assert out == ""


def test_build_wraps_seeded_memory(tmp_path: Path) -> None:
    """Verify a seeded store yields a wrapped block carrying each section."""
    # Given a seeded store
    store = _store(tmp_path)
    _seed(store)
    # When building the injection
    out = Injector(store, RecallConfig()).build()
    # Then the block is wrapped and carries learnings and backlog
    assert out.startswith("<recall-memory>")
    assert out.endswith("</recall-memory>")
    assert "The X gotcha" in out
    assert "tiny thing" in out


def test_learnings_index_omits_body(tmp_path: Path) -> None:
    """Verify the index shows the summary and read-when hint but not the body."""
    # Given a seeded store
    store = _store(tmp_path)
    _seed(store)
    out = Injector(store, RecallConfig()).build()
    # Then the summary and hint appear and the body does not
    assert "The X gotcha" in out
    assert "touching X" in out
    assert "body" not in out


def test_backlog_summary_counts_and_quick_wins(tmp_path: Path) -> None:
    """Verify the backlog summary counts per type and surfaces only [S] quick-wins."""
    # Given a seeded backlog with fix/feat sections
    store = _store(tmp_path)
    _seed(store)
    out = Injector(store, RecallConfig()).build()
    # Then totals, per-type counts, and the [S] item appear; [L]/[M] are not inlined
    assert "3 deferred" in out
    assert "2 fix" in out
    assert "1 feat" in out
    assert "tiny thing" in out
    assert "big thing" not in out


def test_backlog_ignores_blank_header(tmp_path: Path) -> None:
    """Verify a header with no type word does not produce an empty-type count."""
    # Given a backlog whose first section header has no type word
    store = _store(tmp_path)
    store.data_dir.mkdir(parents=True)
    store.backlog_path.write_text(
        "## \n- [ ] [S] orphan — 2026-06-26\n## fix\n- [ ] [M] real — 2026-06-26\n",
        encoding="utf-8",
    )
    out = Injector(store, RecallConfig()).build()
    # Then only the well-formed section is counted; no blank/orphan artifacts
    assert "1 deferred" in out
    assert "1 fix" in out
    assert "orphan" not in out
