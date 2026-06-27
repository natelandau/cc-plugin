#!/usr/bin/env -S uv run --script

# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///

"""SessionStart hook: inject this project's memory and save the transcript pointer.

Reads the durable store for the current project, returns its memory as
non-blocking `additionalContext`, and persists the session's transcript path so
the end-of-session sweep can locate it even after `/clear`. No-ops when running
inside the headless sweep agent or when injection is disabled. Fail-open: any
error exits 0 rather than wedging session start.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
from pathlib import Path

HOOKS_ROOT = Path(__file__).resolve().parent
if str(HOOKS_ROOT) not in sys.path:
    sys.path.insert(0, str(HOOKS_ROOT))

from recall.config import RecallConfig  # noqa: E402
from recall.headless import is_headless  # noqa: E402
from recall.injector import Injector  # noqa: E402
from recall.io import read_payload  # noqa: E402
from recall.store import Store  # noqa: E402


def main() -> None:
    """Inject memory for the current project unless headless or disabled."""
    if is_headless():
        return
    payload = read_payload()
    cfg = RecallConfig.load(project_dir=os.environ.get("CLAUDE_PROJECT_DIR"))
    if not cfg.inject_enabled:
        return
    store = Store.for_cwd(cwd=Path(payload.get("cwd") or Path.cwd()), env=os.environ)
    store.save_transcript_pointer(payload.get("transcript_path") or "")
    text = Injector(store, cfg).build()
    if text:
        print(  # noqa: T201
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "SessionStart",
                        "additionalContext": text,
                    }
                }
            )
        )


if __name__ == "__main__":
    with contextlib.suppress(Exception):  # fail-open: a hook never wedges the session
        main()
    sys.exit(0)
