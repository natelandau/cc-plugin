#!/usr/bin/env -S uv run --script

# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///

"""PreCompact hook: trigger the memory sweep before compaction discards context.

Gating (lock, threshold, transcript window) runs inline; the heavy `claude -p`
pass runs in a detached worker that outlives compaction. No-ops when running
inside the headless sweep agent or when the sweep is disabled. Fail-open: any
error exits 0 rather than blocking compaction.
"""

from __future__ import annotations

import contextlib
import os
import sys
from pathlib import Path

HOOKS_ROOT = Path(__file__).resolve().parent
if str(HOOKS_ROOT) not in sys.path:
    sys.path.insert(0, str(HOOKS_ROOT))

from recall.config import RecallConfig  # noqa: E402
from recall.headless import is_headless  # noqa: E402
from recall.io import read_payload  # noqa: E402
from recall.sweep import run_sweep  # noqa: E402


def main() -> None:
    """Trigger the memory sweep unless headless or disabled."""
    if is_headless():
        return
    payload = read_payload()
    cfg = RecallConfig.load(project_dir=os.environ.get("CLAUDE_PROJECT_DIR"))
    if not cfg.sweep_enabled:
        return
    run_sweep(payload, env=os.environ)


if __name__ == "__main__":
    with contextlib.suppress(Exception):  # fail-open: a hook never wedges the session
        main()
    sys.exit(0)
