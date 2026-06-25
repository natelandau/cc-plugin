#!/usr/bin/env -S uv run --script

# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///

"""PreToolUse dispatcher: route the tool call through this stage's plugins."""

from __future__ import annotations

import sys
from pathlib import Path

HOOKS_ROOT = Path(__file__).resolve().parent
if str(HOOKS_ROOT) not in sys.path:
    sys.path.insert(0, str(HOOKS_ROOT))

from lib.config import load_config  # noqa: E402
from lib.dispatch import run_stage  # noqa: E402
from lib.io import emit_pretooluse, read_payload  # noqa: E402


def main() -> None:
    """Entry point for the consolidated PreToolUse hook."""
    payload = read_payload()
    cfg = load_config()
    run_stage(
        stage_dir=HOOKS_ROOT / "pretooluse",
        event=payload,
        cfg=cfg,
        emit=emit_pretooluse,
    )


if __name__ == "__main__":
    main()
