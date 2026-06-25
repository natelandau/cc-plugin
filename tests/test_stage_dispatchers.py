"""End-to-end noop checks: an empty stage dir exits 0 with no decision."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parent.parent / "plugins" / "natelandau-toolkit" / "hooks"

STAGES = ["pretooluse", "posttooluse", "stop", "sessionstart", "sessionend"]


@pytest.mark.parametrize("stage", STAGES)
def test_empty_stage_is_noop(stage):
    proc = subprocess.run(
        [sys.executable, str(HOOKS / f"{stage}.py")],
        input=json.dumps(
            {"hook_event_name": stage, "tool_name": "Bash", "tool_input": {"command": "echo hello"}}
        ),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""
