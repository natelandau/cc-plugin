"""Verify the SessionStart injector: learnings index and backlog pointer."""

from __future__ import annotations

from typing import TYPE_CHECKING

from recall.config import RecallConfig  # ty: ignore[unresolved-import]
from recall.injector import Injector  # ty: ignore[unresolved-import]

from tests.recall._store_factory import store_at

if TYPE_CHECKING:
    from pathlib import Path

    from recall.store import Store  # ty: ignore[unresolved-import]


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
    out = Injector(store_at(tmp_path), RecallConfig()).build()
    # Then nothing is injected
    assert out == ""


def test_build_wraps_seeded_memory(tmp_path: Path) -> None:
    """Verify a seeded store yields a wrapped block carrying each section."""
    # Given a seeded store
    store = store_at(tmp_path)
    _seed(store)
    # When building the injection
    out = Injector(store, RecallConfig()).build()
    # Then the block is wrapped and carries the learning and the backlog pointer
    assert out.startswith("<recall-memory>")
    assert out.endswith("</recall-memory>")
    assert "The X gotcha" in out
    assert "Run /recall-backlog to triage" in out


def test_learnings_index_omits_body(tmp_path: Path) -> None:
    """Verify the index shows the summary and read-when hint but not the body."""
    # Given a seeded store
    store = store_at(tmp_path)
    _seed(store)
    out = Injector(store, RecallConfig()).build()
    # Then the summary and hint appear and the body does not
    assert "The X gotcha" in out
    assert "touching X" in out
    assert "body" not in out


def test_backlog_pointer_counts_open_items_without_body(tmp_path: Path) -> None:
    """Verify the pointer counts open items and never inlines any item body."""
    # Given a seeded backlog with three open items across two sections
    store = store_at(tmp_path)
    _seed(store)
    out = Injector(store, RecallConfig()).build()
    # Then the count and the triage nudge appear, but no item text leaks
    assert "3 items in the deferred backlog" in out
    assert "Run /recall-backlog to triage" in out
    assert "tiny thing" not in out
    assert "big thing" not in out


def test_backlog_pointer_counts_all_sections_singular(tmp_path: Path) -> None:
    """Verify the count spans every section (no header gating) and reads singular at one."""
    # Given a single open item that lives under a blank header
    store = store_at(tmp_path)
    store.data_dir.mkdir(parents=True)
    store.backlog_path.write_text(
        "## \n- [ ] [S] orphan — 2026-06-26\n",
        encoding="utf-8",
    )
    out = Injector(store, RecallConfig()).build()
    # Then it is counted regardless of header, with singular "item"
    assert "1 item in the deferred backlog" in out


def test_backlog_pointer_skips_when_all_done(tmp_path: Path) -> None:
    """Verify a backlog with no open items injects no pointer."""
    # Given a backlog whose every item is checked off
    store = store_at(tmp_path)
    store.data_dir.mkdir(parents=True)
    store.backlog_path.write_text(
        "## fix\n- [x] done thing — 2026-06-26\n",
        encoding="utf-8",
    )
    # When building with no learnings to carry the block
    out = Injector(store, RecallConfig()).build()
    # Then nothing is injected
    assert out == ""


def test_backlog_only_store_injects_pointer(tmp_path: Path) -> None:
    """Verify a store with a backlog but no learnings still injects the pointer."""
    # Given a store with open backlog items and no learnings
    store = store_at(tmp_path)
    store.data_dir.mkdir(parents=True)
    store.backlog_path.write_text(
        "## fix\n- [ ] [M] real — 2026-06-26\n",
        encoding="utf-8",
    )
    out = Injector(store, RecallConfig()).build()
    # Then the wrapped block carries the pointer without a learnings index
    assert out.startswith("<recall-memory>")
    assert "1 item in the deferred backlog" in out
    assert "## Learnings Index" not in out
