"""Verify each recall stage dispatcher with no plugins exits 0 silently."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parent.parent.parent / "plugins" / "natelandau-recall" / "hooks"


@pytest.mark.parametrize("stage", ["sessionstart", "sessionend", "precompact"])
def test_empty_stage_is_noop(stage: str) -> None:
    """Verify a stage with an empty registry exits 0 with no stdout."""
    # Given a stage dispatcher with no registered plugins
    # When a minimal payload is piped through it
    proc = subprocess.run(
        [str(HOOKS / f"{stage}.py")],
        input=json.dumps({"hook_event_name": stage, "source": "startup"}),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    # Then it exits cleanly and emits nothing
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == ""
