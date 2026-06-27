"""SessionStart plugin: inject this project's memory and save the transcript pointer.

Reads the durable store for the current project (resolved from cwd) and returns
its memory as non-blocking `additionalContext`. Also persists the session's
`transcript_path` to the ephemeral state dir so the end-of-session sweep can
locate the transcript even after `/clear`. Pure read side: never writes memory.
See spec §5.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from lib import memory, store
from lib.io import Decision

if TYPE_CHECKING:
    from lib.config import Config

ID = "inject-memory"
DEFAULT_ARCH_MAX_BYTES = 4096


def _save_transcript_pointer(key: str, transcript_path: str) -> None:
    """Best-effort persist the transcript path for the sweep; never raises."""
    if not transcript_path:
        return
    try:
        sd = store.state_dir(key, env=os.environ)
        sd.mkdir(parents=True, exist_ok=True)
        (sd / "transcript-path").write_text(transcript_path, encoding="utf-8")
    except OSError:
        pass


def evaluate(event: dict[str, Any], cfg: Config) -> Decision | None:
    """Return this project's memory as advisory context, or None when empty."""
    cwd = Path(event.get("cwd") or Path.cwd())
    key = store.project_key(cwd=cwd, env=os.environ)
    _save_transcript_pointer(key, event.get("transcript_path") or "")

    data = store.data_dir(key, env=os.environ)
    max_bytes = cfg.int_option("inject-memory", "architecture_max_bytes", DEFAULT_ARCH_MAX_BYTES)
    injection = memory.build_injection(data, architecture_max_bytes=max_bytes)
    if not injection:
        return None
    return Decision(block=False, context=injection)
