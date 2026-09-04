"""Full-path PreToolUse dispatcher checks."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HOOKS = Path(__file__).resolve().parent.parent / "plugins" / "natelandau-toolkit" / "hooks"


def _run(payload: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HOOKS / "pretooluse.py")],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
    )


def test_protect_system_blocks_through_dispatcher() -> None:
    """Verify a destructive system command is blocked through the dispatcher."""
    # Destructive string is DATA fed to the hook on stdin; it is never executed.
    proc = _run({"tool_name": "Bash", "tool_input": {"command": "rm -rf /etc"}})
    assert proc.returncode == 2
    assert "BLOCKED" in proc.stderr


def test_benign_command_passes_through() -> None:
    """Verify a benign command exits 0 through the dispatcher."""
    proc = _run({"tool_name": "Bash", "tool_input": {"command": "ls /tmp"}})
    assert proc.returncode == 0


def test_uv_nudge_emits_advisory_context(tmp_path: Path) -> None:
    """Verify the use-uv advisory reaches additionalContext through the dispatcher."""
    # Given a project whose venv provides pytest (the nudge is gated on that)
    venv_bin = tmp_path / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    (tmp_path / ".venv" / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
    (venv_bin / "pytest").write_text("#!/bin/sh\n", encoding="utf-8")

    proc = _run({"tool_name": "Bash", "tool_input": {"command": "pytest -q"}, "cwd": str(tmp_path)})
    assert proc.returncode == 0
    ctx = json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "uv run pytest" in ctx
