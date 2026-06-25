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

from lib import transcript  # noqa: E402
from lib.config import load_config  # noqa: E402
from lib.dispatch import run_stage  # noqa: E402
from lib.io import emit_stop, read_payload  # noqa: E402


def parse_stop(payload: dict) -> dict:
    """Read and parse the transcript once, exposing it to every Stop plugin.

    Stop input carries no assistant text directly, only a `transcript_path`.
    Reading and reconstructing the closing message here means each plugin
    sees `assistant_message` and `entries` without re-reading the JSONL.
    """
    transcript_path = payload.get("transcript_path")
    entries = transcript.read_entries(transcript_path) if transcript_path else []
    return {
        **payload,
        "entries": entries,
        "assistant_message": transcript.last_assistant_message_text(entries),
    }


def main() -> None:
    """Entry point for the consolidated Stop hook."""
    payload = read_payload()
    # Re-fired this turn: let the assistant stop, never loop.
    if payload.get("stop_hook_active"):
        sys.exit(0)
    cfg = load_config()
    run_stage(
        stage_dir=HOOKS_ROOT / "stop",
        event=parse_stop(payload),
        cfg=cfg,
        emit=emit_stop,
    )


if __name__ == "__main__":
    main()
