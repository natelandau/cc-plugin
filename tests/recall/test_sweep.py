"""Verify the sweep gate: lock acquisition, stale-lock stealing, and exchange threshold."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path
    from types import ModuleType

    import pytest


@dataclass(frozen=True)
class _Cfg:
    """Minimal Config stand-in for sweep tests."""

    profile: str = "standard"
    disabled_hooks: frozenset[str] = frozenset()
    project_dir: str | None = None
    hook_options: dict[str, dict[str, str]] = field(default_factory=dict)
    min_exchanges: int = 5

    def option(self, hook_id: str, key: str, default: str) -> str:
        """Return a per-hook string option or the default."""
        return default

    def int_option(self, hook_id: str, key: str, default: int) -> int:
        """Return min_exchanges when queried for sweep, else default."""
        if hook_id == "sweep" and key == "min_exchanges":
            return self.min_exchanges
        return default


# ---------------------------------------------------------------------------
# JSONL transcript helpers (mirror the shape produced by Claude Code)
# ---------------------------------------------------------------------------


def _user(text: str) -> dict:
    """Build a user entry with a plain-string content field."""
    return {"type": "user", "message": {"role": "user", "content": text}}


def _assistant(text: str) -> dict:
    """Build an assistant entry with a single text block."""
    return {
        "type": "assistant",
        "message": {
            "id": "msg_a",
            "role": "assistant",
            "content": [{"type": "text", "text": text}],
        },
    }


def _write_transcript(path: Path, entries: list[dict]) -> None:
    """Write a JSONL transcript file at the given path."""
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")


def _meaningful_entries(n: int) -> list[dict]:
    """Build n interleaved user/assistant entries, all meaningful (no noise)."""
    entries: list[dict] = []
    for i in range(n):
        if i % 2 == 0:
            entries.append(_user(f"User message {i}"))
        else:
            entries.append(_assistant(f"Assistant response {i}"))
    return entries


# ---------------------------------------------------------------------------
# acquire_lock tests
# ---------------------------------------------------------------------------


def test_acquire_lock_succeeds_on_first_call(
    tmp_path: Path,
    import_recall_module: Callable[[str], ModuleType],
) -> None:
    """Verify acquire_lock returns a lock path when the lock does not yet exist."""
    # Given an empty state dir and a fresh timestamp
    sweep = import_recall_module("lib.sweep")
    state_dir = tmp_path / "state"
    now = 1000.0

    # When acquiring the lock for the first time
    lock = sweep.acquire_lock(state_dir, now=now)

    # Then a path is returned, the file exists, and stores the timestamp
    assert lock is not None
    assert lock.exists()
    assert float(lock.read_text(encoding="utf-8").strip()) == now


def test_acquire_lock_second_call_returns_none_held(
    tmp_path: Path,
    import_recall_module: Callable[[str], ModuleType],
) -> None:
    """Verify a second acquire_lock with the same timestamp returns None (lock held)."""
    # Given an already-acquired fresh lock
    sweep = import_recall_module("lib.sweep")
    state_dir = tmp_path / "state"
    now = 1000.0
    first = sweep.acquire_lock(state_dir, now=now)
    assert first is not None

    # When acquiring again with the same now (well within stale_after)
    second = sweep.acquire_lock(state_dir, now=now)

    # Then the second attempt fails because the lock is still fresh
    assert second is None


def test_acquire_lock_steals_stale_lock(
    tmp_path: Path,
    import_recall_module: Callable[[str], ModuleType],
) -> None:
    """Verify a lock older than stale_after is stolen on a subsequent acquire."""
    # Given a lock acquired at now=1000 with a 300s stale window
    sweep = import_recall_module("lib.sweep")
    state_dir = tmp_path / "state"
    first = sweep.acquire_lock(state_dir, now=1000.0, stale_after=300.0)
    assert first is not None

    # When acquiring 400s later (past the 300s threshold)
    second = sweep.acquire_lock(state_dir, now=1400.0, stale_after=300.0)

    # Then the stale lock is stolen and a new lock is returned with the new timestamp
    assert second is not None
    assert float(second.read_text(encoding="utf-8").strip()) == 1400.0


def test_acquire_lock_fresh_lock_not_stolen(
    tmp_path: Path,
    import_recall_module: Callable[[str], ModuleType],
) -> None:
    """Verify a lock within stale_after is not stolen."""
    # Given a lock acquired at now=1000 with a 300s stale window
    sweep = import_recall_module("lib.sweep")
    state_dir = tmp_path / "state"
    first = sweep.acquire_lock(state_dir, now=1000.0, stale_after=300.0)
    assert first is not None

    # When acquiring 200s later (within the 300s stale window)
    second = sweep.acquire_lock(state_dir, now=1200.0, stale_after=300.0)

    # Then the fresh lock is not stolen and None is returned
    assert second is None


# ---------------------------------------------------------------------------
# gate tests
# ---------------------------------------------------------------------------


def test_gate_returns_none_and_releases_lock_below_threshold(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    import_recall_module: Callable[[str], ModuleType],
) -> None:
    """Verify gate returns None and releases the lock when below min_exchanges."""
    # Given a project with a sparse transcript (2 entries) and a threshold of 5
    proj = tmp_path / "proj"
    proj.mkdir()
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj))

    t_file = tmp_path / "sparse.jsonl"
    _write_transcript(t_file, [_user("hello"), _assistant("hi")])

    sweep = import_recall_module("lib.sweep")
    store = import_recall_module("lib.store")
    env = dict(os.environ)
    key = store.project_key(cwd=proj, env=env)
    state_dir_path = store.state_dir(key, env=env)

    event: dict = {"cwd": str(proj), "transcript_path": str(t_file)}
    cfg = _Cfg(min_exchanges=5)

    # When gate is called with only 2 meaningful messages (< 5 threshold)
    result = sweep.gate(event, cfg, now=1000.0)

    # Then None is returned and the lock file is cleaned up
    assert result is None
    assert not (state_dir_path / "sweep.lock").exists()


def test_gate_returns_sweep_job_above_threshold(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    import_recall_module: Callable[[str], ModuleType],
) -> None:
    """Verify gate returns a SweepJob with the windowed entries when >= min_exchanges."""
    # Given a project with a rich transcript (6 meaningful entries, threshold=5)
    proj = tmp_path / "proj"
    proj.mkdir()
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj))

    entries = _meaningful_entries(6)
    t_file = tmp_path / "rich.jsonl"
    _write_transcript(t_file, entries)

    sweep = import_recall_module("lib.sweep")
    event: dict = {"cwd": str(proj), "transcript_path": str(t_file)}
    cfg = _Cfg(min_exchanges=5)

    # When gate is called with 6 meaningful messages (>= 5 threshold)
    result = sweep.gate(event, cfg, now=1000.0)

    # Then a SweepJob is returned, the lock stays held, and the window covers all entries
    assert result is not None
    assert result.transcript_path == str(t_file)
    assert len(result.window) == len(entries)
    # Lock is held on success (not released — the run step owns release)
    assert (result.state_dir / "sweep.lock").exists()


def test_gate_falls_back_to_transcript_pointer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    import_recall_module: Callable[[str], ModuleType],
) -> None:
    """Verify gate reads the transcript path from the state-dir pointer when event path is empty."""
    # Given a project whose state dir has a saved transcript-path pointer
    proj = tmp_path / "proj"
    proj.mkdir()
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj))

    entries = _meaningful_entries(6)
    t_file = tmp_path / "session.jsonl"
    _write_transcript(t_file, entries)

    # Compute the expected state_dir and write the transcript-path pointer into it
    sweep = import_recall_module("lib.sweep")
    store = import_recall_module("lib.store")
    env = dict(os.environ)
    key = store.project_key(cwd=proj, env=env)
    state_dir_path = store.state_dir(key, env=env)
    state_dir_path.mkdir(parents=True, exist_ok=True)
    (state_dir_path / "transcript-path").write_text(str(t_file), encoding="utf-8")

    # When gate is called with an empty transcript_path in the event
    event: dict = {"cwd": str(proj), "transcript_path": ""}
    cfg = _Cfg(min_exchanges=5)
    result = sweep.gate(event, cfg, now=1000.0)

    # Then a SweepJob is returned, using the path from the saved pointer
    assert result is not None
    assert result.transcript_path == str(t_file)
    assert len(result.window) == len(entries)
