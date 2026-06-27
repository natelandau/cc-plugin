"""Verify the SessionStart injector emits memory context and saves the transcript pointer."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import ModuleType

    import pytest

HOOKS = Path(__file__).resolve().parent.parent.parent / "plugins" / "natelandau-recall" / "hooks"


@dataclass(frozen=True)
class _Cfg:
    profile: str = "standard"
    disabled_hooks: frozenset[str] = frozenset()
    project_dir: str | None = None
    hook_options: dict[str, dict[str, str]] = field(default_factory=dict)

    def option(self, hook_id: str, key: str, default: str) -> str:
        """Return a per-hook string option, or default when unset."""
        return self.hook_options.get(hook_id, {}).get(key, default)

    def int_option(self, hook_id: str, key: str, default: int) -> int:
        """Return a per-hook integer option, or default when unset."""
        return default


def _seed_store(proj: Path, env_home: Path, store_mod: ModuleType) -> None:
    """Write one learning file into the project's data store."""
    key = store_mod.encode_project_key(proj.resolve())
    data = env_home / "natelandau-recall" / key / store_mod.LEARNINGS_DIRNAME
    data.mkdir(parents=True)
    (data / "x.md").write_text(
        '---\nsummary: The X gotcha\nread_when: ["touching X"]\n---\nbody\n', encoding="utf-8"
    )


def test_injects_when_store_nonempty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    import_recall_module: Callable[[str], ModuleType],
) -> None:
    """Verify a non-empty store produces a non-blocking context Decision."""
    # Given a project whose store has a learning, with XDG redirected to tmp
    proj = tmp_path / "proj"
    proj.mkdir()
    xdg = tmp_path / "data"
    monkeypatch.setenv("XDG_DATA_HOME", str(xdg))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj))
    store_mod = import_recall_module("lib.store")
    _seed_store(proj, xdg, store_mod)
    inject_memory = import_recall_module("sessionstart.inject_memory")

    # When the injector evaluates a startup event from the project
    event = {"cwd": str(proj), "transcript_path": str(tmp_path / "t.jsonl"), "source": "startup"}
    decision = inject_memory.evaluate(event, _Cfg(project_dir=str(proj)))

    # Then it returns advisory context naming the learning, not a block
    assert decision is not None
    assert decision.block is False
    assert "The X gotcha" in decision.context


def test_saves_transcript_pointer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    import_recall_module: Callable[[str], ModuleType],
) -> None:
    """Verify the transcript path is persisted to the state dir for the sweep."""
    # Given a redirected state root and a transcript path on the event
    proj = tmp_path / "proj"
    proj.mkdir()
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    state_home = tmp_path / "state"
    monkeypatch.setenv("XDG_STATE_HOME", str(state_home))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj))
    store_mod = import_recall_module("lib.store")
    inject_memory = import_recall_module("sessionstart.inject_memory")

    # When the injector evaluates with a transcript path
    event = {"cwd": str(proj), "transcript_path": "/tmp/x/t.jsonl", "source": "startup"}  # noqa: S108
    inject_memory.evaluate(event, _Cfg(project_dir=str(proj)))

    # Then the pointer file holds that path
    key = store_mod.encode_project_key(proj.resolve())
    pointer = store_mod.state_dir(key, env={"XDG_STATE_HOME": str(state_home)}) / "transcript-path"
    assert pointer.read_text(encoding="utf-8").strip() == "/tmp/x/t.jsonl"  # noqa: S108


def test_empty_store_returns_none(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    import_recall_module: Callable[[str], ModuleType],
) -> None:
    """Verify an empty store injects nothing."""
    # Given a project with no store
    proj = tmp_path / "proj"
    proj.mkdir()
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj))
    inject_memory = import_recall_module("sessionstart.inject_memory")

    # When the injector evaluates
    event = {"cwd": str(proj), "transcript_path": "", "source": "startup"}
    decision = inject_memory.evaluate(event, _Cfg(project_dir=str(proj)))

    # Then nothing is injected
    assert decision is None


def test_dispatcher_injects_context(
    tmp_path: Path,
    import_recall_module: Callable[[str], ModuleType],
) -> None:
    """Verify the sessionstart dispatcher emits additionalContext with the seeded learning."""
    # Given a seeded store with XDG roots redirected to tmp, in a fresh subprocess
    proj = tmp_path / "proj"
    proj.mkdir()
    xdg_data = tmp_path / "data"
    xdg_state = tmp_path / "state"

    # Seed the store directly using the recall lib (isolated via fixture)
    store_mod = import_recall_module("lib.store")
    key = store_mod.encode_project_key(proj.resolve())
    learning_dir = xdg_data / "natelandau-recall" / key / store_mod.LEARNINGS_DIRNAME
    learning_dir.mkdir(parents=True)
    (learning_dir / "x.md").write_text(
        '---\nsummary: The X gotcha\nread_when: ["touching X"]\n---\nbody\n', encoding="utf-8"
    )

    # When a SessionStart payload is piped through the dispatcher with env overrides
    # Inherit the full environment so uv is on PATH, then override the XDG/project vars
    env = {
        **os.environ,
        "XDG_DATA_HOME": str(xdg_data),
        "XDG_STATE_HOME": str(xdg_state),
        "CLAUDE_PROJECT_DIR": str(proj),
    }
    payload = json.dumps(
        {
            "hook_event_name": "SessionStart",
            "cwd": str(proj),
            "transcript_path": str(tmp_path / "t.jsonl"),
            "source": "startup",
        }
    )
    proc = subprocess.run(
        [str(HOOKS / "sessionstart.py")],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=30,
    )

    # Then it exits 0 and the output contains the seeded learning in additionalContext
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    context = out["hookSpecificOutput"]["additionalContext"]
    assert "The X gotcha" in context
