#!/usr/bin/env -S uv run --script

# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///

"""Stop dispatcher: parse the transcript once, route to this stage's plugins."""

from __future__ import annotations

import sys
from pathlib import Path

HOOKS_ROOT = Path(__file__).resolve().parent
if str(HOOKS_ROOT) not in sys.path:
    sys.path.insert(0, str(HOOKS_ROOT))

from lib.dispatch import run_dispatcher  # noqa: E402
from lib.transcript import parse_stop  # noqa: E402

if __name__ == "__main__":
    # prepare: reconstruct the closing assistant message for every Stop plugin.
    # skip_if: bail when re-fired this turn so a block can never loop.
    run_dispatcher(
        "stop",
        prepare=parse_stop,
        skip_if=lambda payload: bool(payload.get("stop_hook_active")),
    )
