"""Verify each recall stage dispatcher exits 0 silently against an empty, isolated store.

These tests run the real dispatcher subprocess but isolate it from any real recall
state on the machine. Each case uses a fresh tmp_path as XDG_DATA_HOME and
XDG_STATE_HOME so there is no existing memory store or sweep state to read.
CLAUDE_PROJECT_DIR is pointed at an empty tmp dir.

For sessionend and precompact the NL_RECALL_HEADLESS guard is also set as
belt-and-suspenders: it causes the sweep recursion guard to short-circuit before
any fork even if state somehow leaked through the empty-store gate.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parent.parent.parent / "plugins" / "natelandau-recall" / "hooks"


@pytest.mark.parametrize("stage", ["sessionstart", "sessionend", "precompact"])
def test_stage_exits_cleanly_with_empty_isolated_store(stage: str, tmp_path: Path) -> None:
    """Verify each stage dispatcher exits 0 with empty stdout when run against an empty isolated store."""
    # Given an isolated environment with no recall data and no real project dir
    proj = tmp_path / "proj"
    proj.mkdir()
    env = {
        **os.environ,
        "XDG_DATA_HOME": str(tmp_path / "data"),
        "XDG_STATE_HOME": str(tmp_path / "state"),
        "CLAUDE_PROJECT_DIR": str(proj),
    }
    # Belt-and-suspenders for sweep stages: headless guard short-circuits before any fork
    # even if state leaks through the empty-store gate
    if stage in ("sessionend", "precompact"):
        env["NL_RECALL_HEADLESS"] = "1"

    # When a minimal payload is piped through the dispatcher
    proc = subprocess.run(
        [str(HOOKS / f"{stage}.py")],
        input=json.dumps({"hook_event_name": stage, "source": "startup"}),
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=30,
    )

    # Then it exits cleanly and emits nothing to stdout
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == ""
