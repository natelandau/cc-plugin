"""Full-path Stop dispatcher checks, including the stop_hook_active bail.

Invokes hooks/stop.py as a subprocess with a payload on stdin (payloads are
inert data; nothing destructive runs here). Stop is a ready-noop stage (no
registered plugins), so these cover the dispatcher scaffolding itself: the
bail-on-re-fire path, the missing-transcript noop, and that a parsed transcript
still yields no block while the stage has no plugins.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

HOOKS = Path(__file__).resolve().parent.parent / "plugins" / "natelandau-toolkit" / "hooks"


def _run(payload: dict[str, Any]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HOOKS / "stop.py")],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


def _assistant_text_entry(text: str, message_id: str = "msg-1") -> dict[str, Any]:
    return {
        "type": "assistant",
        "message": {
            "id": message_id,
            "role": "assistant",
            "content": [{"type": "text", "text": text}],
        },
    }


def _write_transcript(tmp_path: Path, entries: Iterable[dict[str, Any]]) -> Path:
    path = tmp_path / "transcript.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
    return path


def test_stop_hook_active_bails_silently() -> None:
    """Verify a re-fired Stop hook exits 0 with no output."""
    # Given a payload marked as a re-fire
    # When the dispatcher runs
    proc = _run({"stop_hook_active": True, "transcript_path": "/nonexistent"})

    # Then it bails silently
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""


def test_missing_transcript_is_noop() -> None:
    """Verify an empty transcript_path produces no block."""
    # Given a payload with no transcript to read
    # When the dispatcher runs
    proc = _run({"transcript_path": ""})

    # Then it exits 0 with no decision
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""


def test_noop_stage_yields_no_block(tmp_path: Path) -> None:
    """Verify a parsed transcript yields no block while Stop has no plugins."""
    # Given a transcript with a normal closing assistant message
    transcript = _write_transcript(
        tmp_path, [_assistant_text_entry("Made the changes; tests pass. Ready for review.")]
    )

    # When the dispatcher runs over it
    proc = _run({"hook_event_name": "Stop", "transcript_path": str(transcript)})

    # Then it exits 0 with no decision (the stage is a ready noop)
    assert proc.returncode == 0, f"stderr={proc.stderr!r}"
    assert proc.stdout.strip() == ""
