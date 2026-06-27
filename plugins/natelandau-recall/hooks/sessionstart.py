#!/usr/bin/env -S uv run --script

# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///

"""SessionStart hook: inject this project's memory and consume any pending handoff.

Reads the durable store for the current project, returns its memory as
non-blocking `additionalContext`, and persists the session's transcript path so
the end-of-session sweep can locate it even after `/clear`. Independently, on any
start other than `resume` it injects the consume-once `HANDOFF.md` the user wrote,
ahead of the memory block, and deletes it only after the inject is emitted. The
handoff is an explicit user artifact, so it is carried even when memory injection
is disabled. No-ops when running inside the headless sweep agent. Fail-open: any
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


def _write_all(fd: int, data: bytes) -> None:
    """Write every byte of `data` to `fd`, looping past short writes.

    A single os.write may accept fewer bytes than given (e.g. a nearly-full pipe
    buffer) without raising, so one call cannot be trusted to have emitted the
    whole payload; a partial write would otherwise truncate the JSON.
    """
    while data:
        written = os.write(fd, data)
        data = data[written:]


def main() -> None:
    """Inject the handoff (if any) and memory for the current project, unless headless."""
    if is_headless():
        return
    payload = read_payload()
    cfg = RecallConfig.load(project_dir=os.environ.get("CLAUDE_PROJECT_DIR"))

    # Consume the handoff on any start except `resume` (which may be the same session
    # that wrote it). A denylist, not an allowlist of known sources, keeps this working
    # if upstream adds a start source, and consumes rather than stranding the baton on
    # an unknown or missing source.
    consume_handoff = payload.get("source") != "resume"
    if not (consume_handoff or cfg.inject_enabled):
        return  # resume with injection off: nothing to do, skip store resolution (git)

    store = Store.for_cwd(cwd=Path(payload.get("cwd") or Path.cwd()), env=os.environ)
    blocks: list[str] = []

    # Handoff first (freshest, most task-specific) and independent of inject config,
    # since the user explicitly created it. Read now, delete only after a clean emit.
    handoff_text = store.read_handoff() if consume_handoff else None
    if handoff_text:
        blocks.append(handoff_text)

    if cfg.inject_enabled:
        store.save_transcript_pointer(payload.get("transcript_path") or "")
        memory = Injector(store, cfg).build()
        if memory:
            blocks.append(memory)

    if not blocks:
        return

    rendered = json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": "\n\n".join(blocks),
            }
        }
    )
    # Write unbuffered so a broken stdout fails synchronously here, rather than
    # leaving buffered output for interpreter shutdown to choke on (which would
    # override the fail-open exit 0). The baton is retired only after the whole
    # payload is confirmed written, so a failed or partial emit never loses it.
    try:
        _write_all(sys.stdout.fileno(), (rendered + "\n").encode("utf-8"))
    except OSError:
        return
    if handoff_text:
        store.delete_handoff()


if __name__ == "__main__":
    with contextlib.suppress(Exception):  # fail-open: a hook never wedges the session
        main()
    sys.exit(0)
