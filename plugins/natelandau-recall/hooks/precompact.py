#!/usr/bin/env -S uv run --script

# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///

"""PreCompact dispatcher: trigger the memory sweep before compaction, unless headless."""

from __future__ import annotations

import sys
from pathlib import Path

HOOKS_ROOT = Path(__file__).resolve().parent
if str(HOOKS_ROOT) not in sys.path:
    sys.path.insert(0, str(HOOKS_ROOT))

from lib.dispatch import run_dispatcher  # noqa: E402
from lib.headless import is_headless  # noqa: E402

if __name__ == "__main__":
    run_dispatcher("precompact", skip_if=lambda _payload: is_headless())
