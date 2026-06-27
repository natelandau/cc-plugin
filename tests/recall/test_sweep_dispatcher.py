"""Dispatcher-level tests for the SessionEnd/PreCompact sweep integration.

These tests pipe payloads through the real dispatcher scripts but are written
so the gate always bails before any fork: either the headless guard short-circuits
immediately, or the transcript is below the minimum-exchanges threshold so
gate() returns None and _spawn_detached is never called. No real `claude`
process is spawned, and _spawn_detached is never exercised here.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

HOOKS = Path(__file__).resolve().parent.parent.parent / "plugins" / "natelandau-recall" / "hooks"


def test_sessionend_headless_guard_short_circuits(tmp_path: Path) -> None:
    """Verify the NL_RECALL_HEADLESS env var causes sessionend to exit 0 silently with no side effects."""
    # Given a sessionend payload with the headless guard set
    payload = json.dumps({"hook_event_name": "SessionEnd", "cwd": str(tmp_path)})
    env = {
        **os.environ,
        "NL_RECALL_HEADLESS": "1",
        "XDG_DATA_HOME": str(tmp_path / "data"),
        "XDG_STATE_HOME": str(tmp_path / "state"),
    }

    # When piped through the real dispatcher
    proc = subprocess.run(
        [str(HOOKS / "sessionend.py")],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=30,
    )

    # Then it exits cleanly, emits nothing, and no sweep.log was written
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == ""
    state_dir = tmp_path / "state"
    assert not list(state_dir.rglob("sweep.log")) if state_dir.exists() else True


def test_sessionend_below_threshold_exits_cleanly_without_spawning(tmp_path: Path) -> None:
    """Verify that a below-threshold transcript causes sessionend to exit 0 without spawning a worker."""
    # Given a sessionend payload with no transcript path (0 meaningful exchanges < threshold of 5)
    proj = tmp_path / "proj"
    proj.mkdir()
    payload = json.dumps(
        {
            "hook_event_name": "SessionEnd",
            "cwd": str(proj),
            "transcript_path": "",
        }
    )
    # Build env without NL_RECALL_HEADLESS so the gate path actually runs
    env: dict[str, str] = {k: v for k, v in os.environ.items() if k != "NL_RECALL_HEADLESS"}
    env["XDG_DATA_HOME"] = str(tmp_path / "data")
    env["XDG_STATE_HOME"] = str(tmp_path / "state")
    env["CLAUDE_PROJECT_DIR"] = str(proj)

    # When piped through the real dispatcher (gate bails below threshold → no fork)
    proc = subprocess.run(
        [str(HOOKS / "sessionend.py")],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=30,
    )

    # Then it exits cleanly and no sweep.log appears (gate returned None, no worker spawned)
    assert proc.returncode == 0, proc.stderr
    state_dir = tmp_path / "state"
    assert not list(state_dir.rglob("sweep.log")) if state_dir.exists() else True


def test_precompact_headless_guard_short_circuits(tmp_path: Path) -> None:
    """Verify the NL_RECALL_HEADLESS env var causes precompact to exit 0 silently with no side effects."""
    # Given a precompact payload with the headless guard set
    payload = json.dumps({"hook_event_name": "PreCompact", "cwd": str(tmp_path)})
    env = {
        **os.environ,
        "NL_RECALL_HEADLESS": "1",
        "XDG_DATA_HOME": str(tmp_path / "data"),
        "XDG_STATE_HOME": str(tmp_path / "state"),
    }

    # When piped through the real dispatcher
    proc = subprocess.run(
        [str(HOOKS / "precompact.py")],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=30,
    )

    # Then it exits cleanly, emits nothing, and no sweep.log was written
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == ""
    state_dir = tmp_path / "state"
    assert not list(state_dir.rglob("sweep.log")) if state_dir.exists() else True


def test_precompact_below_threshold_exits_cleanly_without_spawning(tmp_path: Path) -> None:
    """Verify that a below-threshold transcript causes precompact to exit 0 without spawning a worker."""
    # Given a precompact payload with no transcript path
    proj = tmp_path / "proj"
    proj.mkdir()
    payload = json.dumps(
        {
            "hook_event_name": "PreCompact",
            "cwd": str(proj),
            "transcript_path": "",
        }
    )
    # Build env without NL_RECALL_HEADLESS so the gate path actually runs
    env: dict[str, str] = {k: v for k, v in os.environ.items() if k != "NL_RECALL_HEADLESS"}
    env["XDG_DATA_HOME"] = str(tmp_path / "data")
    env["XDG_STATE_HOME"] = str(tmp_path / "state")
    env["CLAUDE_PROJECT_DIR"] = str(proj)

    # When piped through the real dispatcher
    proc = subprocess.run(
        [str(HOOKS / "precompact.py")],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=30,
    )

    # Then it exits cleanly and no sweep.log appears
    assert proc.returncode == 0, proc.stderr
    state_dir = tmp_path / "state"
    assert not list(state_dir.rglob("sweep.log")) if state_dir.exists() else True
