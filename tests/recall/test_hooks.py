"""End-to-end tests for the three thin hook scripts (env-isolated subprocesses).

Every case sets XDG_DATA_HOME / XDG_STATE_HOME under tmp_path and overrides
CLAUDE_PROJECT_DIR so a script can never read the machine's real recall state.
Sweep cases set NL_RECALL_HEADLESS=1 or stay below the exchange threshold so no
real `claude` is ever spawned and no worker is ever forked.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from recall.store import Store  # ty: ignore[unresolved-import]

from tests._env import clean_environ

HOOKS = Path(__file__).resolve().parent.parent.parent / "plugins" / "natelandau-recall" / "hooks"

# The recursion guard, dropped so a NL_RECALL_HEADLESS leaking from the test
# runner can never change a case's intent; a case that needs it sets it via
# env_overrides. (clean_environ also drops the git location vars so a hook
# resolves the tmp project, not the checkout the suite runs from.)
_RECURSION_GUARD = frozenset({"NL_RECALL_HEADLESS"})


def _run(
    stage: str, payload: dict, env_overrides: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    """Pipe a JSON payload through a real hook script with an isolated environment."""
    env = {**clean_environ(also_drop=_RECURSION_GUARD), **env_overrides}
    return subprocess.run(
        [str(HOOKS / f"{stage}.py")],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=30,
    )


def _isolated_env(tmp_path: Path, proj: Path) -> dict[str, str]:
    return {
        "XDG_DATA_HOME": str(tmp_path / "data"),
        "XDG_STATE_HOME": str(tmp_path / "state"),
        "CLAUDE_PROJECT_DIR": str(proj),
    }


def _seed_learning(tmp_path: Path, proj: Path) -> None:
    """Seed one learning into the project's store under the tmp XDG data root."""
    store = Store.for_cwd(
        cwd=proj, env={"XDG_DATA_HOME": str(tmp_path / "data"), "CLAUDE_PROJECT_DIR": str(proj)}
    )
    store.learnings_dir.mkdir(parents=True)
    (store.learnings_dir / "x.md").write_text(
        '---\nsummary: The X gotcha\nread_when: ["touching X"]\n---\nbody\n', encoding="utf-8"
    )


def _seed_handoff(tmp_path: Path, proj: Path, text: str = "# Handoff\nthe baton") -> Store:
    """Seed a HANDOFF.md into the project's store and return the store."""
    store = Store.for_cwd(
        cwd=proj, env={"XDG_DATA_HOME": str(tmp_path / "data"), "CLAUDE_PROJECT_DIR": str(proj)}
    )
    store.data_dir.mkdir(parents=True, exist_ok=True)
    store.handoff_path.write_text(text, encoding="utf-8")
    return store


# ---------------------------------------------------------------------------
# SessionStart
# ---------------------------------------------------------------------------


def test_sessionstart_empty_store_exits_silently(tmp_path: Path) -> None:
    """Verify SessionStart on an empty store exits 0 with empty stdout."""
    # Given an isolated, empty store
    proj = tmp_path / "proj"
    proj.mkdir()
    # When SessionStart runs
    proc = _run(
        "sessionstart", {"cwd": str(proj), "source": "startup"}, _isolated_env(tmp_path, proj)
    )
    # Then it exits cleanly and injects nothing
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == ""


def test_sessionstart_seeded_store_injects_context(tmp_path: Path) -> None:
    """Verify SessionStart on a seeded store emits the learning as additionalContext."""
    # Given a seeded store
    proj = tmp_path / "proj"
    proj.mkdir()
    _seed_learning(tmp_path, proj)
    # When SessionStart runs
    payload = {"cwd": str(proj), "transcript_path": str(tmp_path / "t.jsonl"), "source": "startup"}
    proc = _run("sessionstart", payload, _isolated_env(tmp_path, proj))
    # Then it injects the learning into additionalContext
    assert proc.returncode == 0, proc.stderr
    context = json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "The X gotcha" in context


def test_sessionstart_saves_transcript_pointer(tmp_path: Path) -> None:
    """Verify SessionStart persists the transcript path to the state dir for the sweep."""
    # Given an isolated store and a transcript path on the event
    proj = tmp_path / "proj"
    proj.mkdir()
    # When SessionStart runs
    _run(
        "sessionstart",
        {"cwd": str(proj), "transcript_path": "/tmp/x/t.jsonl", "source": "startup"},  # noqa: S108
        _isolated_env(tmp_path, proj),
    )
    # Then the pointer file holds that path
    store = Store.for_cwd(
        cwd=proj, env={"XDG_STATE_HOME": str(tmp_path / "state"), "CLAUDE_PROJECT_DIR": str(proj)}
    )
    assert store.read_transcript_pointer() == "/tmp/x/t.jsonl"  # noqa: S108


def test_sessionstart_disabled_inject_exits_silently(tmp_path: Path) -> None:
    """Verify a config with inject disabled suppresses injection even on a seeded store."""
    # Given a seeded store and a project config turning inject off
    proj = tmp_path / "proj"
    (proj / ".claude").mkdir(parents=True)
    (proj / ".claude" / "natelandau-recall.toml").write_text(
        "[inject]\nenabled = false\n", encoding="utf-8"
    )
    _seed_learning(tmp_path, proj)
    # When SessionStart runs
    proc = _run(
        "sessionstart", {"cwd": str(proj), "source": "startup"}, _isolated_env(tmp_path, proj)
    )
    # Then nothing is injected
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == ""


# ---------------------------------------------------------------------------
# SessionStart - handoff consumption
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("source", ["compact", "clear", "startup"])
def test_sessionstart_consumes_handoff_on_fresh_start(source: str, tmp_path: Path) -> None:
    """Verify a handoff is injected and then deleted on compact/clear/startup."""
    # Given a project with a pending handoff
    proj = tmp_path / "proj"
    proj.mkdir()
    store = _seed_handoff(tmp_path, proj)
    # When SessionStart runs from a fresh-context source
    proc = _run("sessionstart", {"cwd": str(proj), "source": source}, _isolated_env(tmp_path, proj))
    # Then the baton is injected and the file is consumed
    assert proc.returncode == 0, proc.stderr
    context = json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "the baton" in context
    assert not store.handoff_path.exists()


def test_sessionstart_consumes_handoff_on_unknown_source(tmp_path: Path) -> None:
    """Verify any non-resume source consumes the handoff (denylist, not allowlist)."""
    # Given a pending handoff and a source string the hook does not enumerate
    proj = tmp_path / "proj"
    proj.mkdir()
    store = _seed_handoff(tmp_path, proj)
    # When SessionStart runs from an unknown future start source
    proc = _run(
        "sessionstart",
        {"cwd": str(proj), "source": "some-new-source"},
        _isolated_env(tmp_path, proj),
    )
    # Then the baton is still injected and consumed rather than stranded
    assert proc.returncode == 0, proc.stderr
    context = json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "the baton" in context
    assert not store.handoff_path.exists()


def test_sessionstart_skips_handoff_on_resume(tmp_path: Path) -> None:
    """Verify resume neither injects nor deletes the handoff (same session may own it)."""
    # Given a project with a pending handoff
    proj = tmp_path / "proj"
    proj.mkdir()
    store = _seed_handoff(tmp_path, proj)
    # When SessionStart runs from a resume
    proc = _run(
        "sessionstart", {"cwd": str(proj), "source": "resume"}, _isolated_env(tmp_path, proj)
    )
    # Then nothing is injected and the baton is left intact
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == ""
    assert store.handoff_path.exists()


def test_sessionstart_consumes_handoff_when_inject_disabled(tmp_path: Path) -> None:
    """Verify the handoff is carried even when memory injection is disabled."""
    # Given a pending handoff and a project config turning inject off
    proj = tmp_path / "proj"
    (proj / ".claude").mkdir(parents=True)
    (proj / ".claude" / "natelandau-recall.toml").write_text(
        "[inject]\nenabled = false\n", encoding="utf-8"
    )
    store = _seed_handoff(tmp_path, proj)
    # When SessionStart runs
    proc = _run(
        "sessionstart", {"cwd": str(proj), "source": "startup"}, _isolated_env(tmp_path, proj)
    )
    # Then the explicit user artifact is still injected and consumed
    assert proc.returncode == 0, proc.stderr
    context = json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "the baton" in context
    assert not store.handoff_path.exists()


def test_sessionstart_handoff_precedes_memory(tmp_path: Path) -> None:
    """Verify the handoff block is emitted ahead of the memory block."""
    # Given a project with both a handoff and a learning
    proj = tmp_path / "proj"
    proj.mkdir()
    _seed_handoff(tmp_path, proj)
    _seed_learning(tmp_path, proj)
    # When SessionStart runs
    proc = _run(
        "sessionstart", {"cwd": str(proj), "source": "startup"}, _isolated_env(tmp_path, proj)
    )
    # Then both appear, handoff first
    assert proc.returncode == 0, proc.stderr
    context = json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
    assert context.index("the baton") < context.index("The X gotcha")


def test_sessionstart_keeps_handoff_when_emit_fails(tmp_path: Path) -> None:
    """Verify a failed inject leaves the handoff in place (delete only after a clean emit)."""
    # Given a pending handoff and a stdout that cannot be written (read end of a pipe)
    proj = tmp_path / "proj"
    proj.mkdir()
    store = _seed_handoff(tmp_path, proj)
    read_fd, write_fd = os.pipe()
    base = clean_environ(also_drop=_RECURSION_GUARD)
    try:
        # When SessionStart tries to emit to an unwritable fd, the flush raises
        proc = subprocess.run(
            [str(HOOKS / "sessionstart.py")],
            input=json.dumps({"cwd": str(proj), "source": "startup"}),
            stdout=read_fd,  # read end is not writable -> os.write fails with EBADF
            stderr=subprocess.PIPE,
            text=True,
            env={**base, **_isolated_env(tmp_path, proj)},
            check=False,
            timeout=30,
        )
    finally:
        os.close(read_fd)
        os.close(write_fd)
    # Then the hook still fails open (exit 0) and the baton survives for a retry
    assert proc.returncode == 0, proc.stderr
    assert store.handoff_path.exists()


# ---------------------------------------------------------------------------
# SessionEnd / PreCompact (sweep) - never spawns a real worker
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("stage", ["sessionend", "precompact"])
def test_sweep_headless_guard_short_circuits(stage: str, tmp_path: Path) -> None:
    """Verify the headless guard makes the sweep scripts exit 0 silently with no side effects."""
    # Given the headless guard set
    proj = tmp_path / "proj"
    proj.mkdir()
    env = {**_isolated_env(tmp_path, proj), "NL_RECALL_HEADLESS": "1"}
    # When the sweep script runs
    proc = _run(stage, {"cwd": str(proj)}, env)
    # Then it exits cleanly, emits nothing, and writes no sweep.log
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == ""
    assert not list((tmp_path / "state").rglob("sweep.log"))


@pytest.mark.parametrize("stage", ["sessionend", "precompact"])
def test_sweep_below_threshold_does_not_spawn(stage: str, tmp_path: Path) -> None:
    """Verify a below-threshold transcript exits 0 without spawning a worker."""
    # Given no transcript (0 meaningful exchanges) and no headless guard
    proj = tmp_path / "proj"
    proj.mkdir()
    # When the sweep script runs
    proc = _run(stage, {"cwd": str(proj), "transcript_path": ""}, _isolated_env(tmp_path, proj))
    # Then it exits cleanly and no sweep.log is written (gate returned None)
    assert proc.returncode == 0, proc.stderr
    assert not list((tmp_path / "state").rglob("sweep.log"))


@pytest.mark.parametrize("stage", ["sessionend", "precompact"])
def test_sweep_disabled_exits_without_gating(stage: str, tmp_path: Path) -> None:
    """Verify a config with sweep disabled exits 0 before any gating."""
    # Given a project config turning the sweep off
    proj = tmp_path / "proj"
    (proj / ".claude").mkdir(parents=True)
    (proj / ".claude" / "natelandau-recall.toml").write_text(
        "[sweep]\nenabled = false\n", encoding="utf-8"
    )
    # When the sweep script runs
    proc = _run(stage, {"cwd": str(proj), "transcript_path": ""}, _isolated_env(tmp_path, proj))
    # Then it exits cleanly with no side effects
    assert proc.returncode == 0, proc.stderr
    assert not list((tmp_path / "state").rglob("sweep.log"))
