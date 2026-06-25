"""Full-path Stop dispatcher checks, including the stop_hook_active bail.

Invokes hooks/stop.py as a subprocess with a payload on stdin (payloads are
inert data; nothing destructive runs here). Covers the bail-on-re-fire path,
the missing-transcript noop, and a positive block routed through parse_stop ->
the stop plugins.
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


def test_phrase_violation_blocks_through_dispatcher(tmp_path: Path) -> None:
    """Verify a violation-bearing closing message blocks via the full Stop path."""
    # Given a transcript whose final assistant message trips the phrase guard
    transcript = _write_transcript(
        tmp_path,
        [_assistant_text_entry("This failure is pre-existing and unrelated to my change.")],
    )

    # When the dispatcher runs over it
    proc = _run({"hook_event_name": "Stop", "transcript_path": str(transcript)})

    # Then a block decision is emitted (exit 0, JSON on stdout)
    assert proc.returncode == 0, f"stderr={proc.stderr!r}"
    decision = json.loads(proc.stdout)
    assert decision["decision"] == "block"
    assert decision["reason"].startswith("STOP HOOK VIOLATION:")


def test_clean_message_passes_through_dispatcher(tmp_path: Path) -> None:
    """Verify a clean closing message yields no block through the full path."""
    # Given a transcript whose final assistant message is clean
    transcript = _write_transcript(
        tmp_path, [_assistant_text_entry("Made the changes; tests pass. Ready for review.")]
    )

    # When the dispatcher runs over it
    proc = _run({"hook_event_name": "Stop", "transcript_path": str(transcript)})

    # Then it exits 0 with no decision
    assert proc.returncode == 0, f"stderr={proc.stderr!r}"
    assert proc.stdout.strip() == ""
