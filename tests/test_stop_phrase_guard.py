"""Characterization tests for stop_phrase_guard.py.

Builds fake JSONL transcripts in a tmp dir, pipes Stop hook payloads
through the hook script, asserts on exit code and (when blocking) the
JSON decision shape and content.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from pathlib import Path


def _assistant_text_entry(text: str) -> dict[str, Any]:
    """Build a JSONL entry representing an assistant text turn."""
    return {
        "type": "assistant",
        "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
    }


def _assistant_tool_use_entry() -> dict[str, Any]:
    """Build an assistant turn that contains only a tool_use block (no text)."""
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [{"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}],
        },
    }


def _user_entry(text: str) -> dict[str, Any]:
    return {"type": "user", "message": {"role": "user", "content": text}}


def _make_transcript(tmpdir: Path, entries: list[dict[str, Any]]) -> Path:
    path = tmpdir / "transcript.jsonl"
    path.write_text(
        "\n".join(json.dumps(e) for e in entries) + ("\n" if entries else ""),
        encoding="utf-8",
    )
    return path


def _run_hook(hook: Path, payload: dict[str, Any]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(hook)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


@dataclass(frozen=True)
class Case:
    id: str
    entries: list[dict[str, Any]]
    stop_hook_active: bool = False
    expect_block: bool = False
    correction_substring: str = ""
    omit_transcript_path: bool = False
    extra_assertions: list[str] = field(default_factory=list)


CASES: tuple[Case, ...] = (
    Case(
        id="clean message: no block",
        entries=[_assistant_text_entry("Made the changes; tests pass. Ready for your review.")],
        expect_block=False,
    ),
    Case(
        id="pre-existing dodge blocked",
        entries=[
            _assistant_text_entry("This failure is pre-existing and unrelated to my change."),
        ],
        expect_block=True,
        correction_substring="NOTHING IS PRE-EXISTING",
    ),
    Case(
        id="case-insensitive match",
        entries=[_assistant_text_entry("PRE-EXISTING failure, leaving as-is.")],
        expect_block=True,
        correction_substring="NOTHING IS PRE-EXISTING",
    ),
    Case(
        id="known limitation dodge blocked",
        entries=[
            _assistant_text_entry("This is a known limitation of the parser; not addressing."),
        ],
        expect_block=True,
        correction_substring="NO KNOWN LIMITATIONS",
    ),
    Case(
        id="future work dodge blocked",
        entries=[_assistant_text_entry("Leaving the cleanup as future work.")],
        expect_block=True,
        correction_substring="NO KNOWN LIMITATIONS",
    ),
    Case(
        id="should I continue blocked",
        entries=[_assistant_text_entry("I've finished step 2. Should I continue with step 3?")],
        expect_block=True,
        correction_substring="Do not ask",
    ),
    Case(
        id="next session deferral blocked",
        entries=[_assistant_text_entry("We can wrap this in the next session.")],
        expect_block=True,
        correction_substring="next session",
    ),
    Case(
        id="pause here blocked",
        entries=[_assistant_text_entry("Let me pause here so you can review.")],
        expect_block=True,
        correction_substring="Do not pause",
    ),
    Case(
        id="stop_hook_active=true bypasses even on violation",
        entries=[_assistant_text_entry("This failure is pre-existing.")],
        stop_hook_active=True,
        expect_block=False,
    ),
    Case(
        id="walks back past trailing user entry to find last assistant text",
        entries=[
            _assistant_text_entry("This is pre-existing."),
            _user_entry("ok"),
        ],
        expect_block=True,
        correction_substring="NOTHING IS PRE-EXISTING",
    ),
    Case(
        id="last assistant entry is tool_use only: skip and check earlier",
        entries=[
            _assistant_text_entry("Made the changes; tests pass. Ready for your review."),
            _assistant_tool_use_entry(),
        ],
        expect_block=False,
    ),
    Case(
        id="multi-block text concatenated",
        entries=[
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "First part is fine. "},
                        {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}},
                        {"type": "text", "text": "But this is pre-existing."},
                    ],
                },
            },
        ],
        expect_block=True,
        correction_substring="NOTHING IS PRE-EXISTING",
    ),
    Case(
        id="empty transcript file: no block",
        entries=[],
        expect_block=False,
    ),
    Case(
        id="missing transcript_path: no block",
        entries=[_assistant_text_entry("This is pre-existing.")],
        expect_block=False,
        omit_transcript_path=True,
    ),
    Case(
        id="multiple violations: first match wins (ordering)",
        entries=[_assistant_text_entry("This failure is pre-existing. Should I continue?")],
        expect_block=True,
        correction_substring="NOTHING IS PRE-EXISTING",
    ),
)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_stop_phrase_guard(case: Case, tmp_path: Path, hooks_dir: Path) -> None:
    """Verify the hook blocks violations and passes clean output through."""
    # Given a transcript file (or no transcript_path at all) and a Stop payload
    hook = hooks_dir / "stop_phrase_guard.py"
    transcript = _make_transcript(tmp_path, case.entries)
    payload: dict[str, Any] = {
        "hook_event_name": "Stop",
        "session_id": "test-session",
        "stop_hook_active": case.stop_hook_active,
    }
    if not case.omit_transcript_path:
        payload["transcript_path"] = str(transcript)

    # When invoking the hook with the payload on stdin
    proc = _run_hook(hook, payload)

    # Then exit is always 0 and stdout matches the expected decision shape
    assert proc.returncode == 0, f"exit={proc.returncode} stderr={proc.stderr!r}"
    if case.expect_block:
        decision = json.loads(proc.stdout)
        assert decision.get("decision") == "block"
        reason = decision.get("reason", "")
        assert reason.startswith("STOP HOOK VIOLATION:"), reason
        if case.correction_substring:
            assert case.correction_substring.lower() in reason.lower()
    else:
        assert not proc.stdout.strip(), f"unexpected stdout: {proc.stdout!r}"


def test_stop_phrase_guard_skips_malformed_lines(tmp_path: Path, hooks_dir: Path) -> None:
    """Verify the hook ignores non-JSON transcript lines and processes valid ones."""
    # Given a transcript with one malformed line followed by a clean assistant turn
    hook = hooks_dir / "stop_phrase_guard.py"
    tpath = tmp_path / "transcript.jsonl"
    tpath.write_text(
        "this is not json\n" + json.dumps(_assistant_text_entry("All good, tests pass.")) + "\n",
        encoding="utf-8",
    )
    payload = {
        "hook_event_name": "Stop",
        "session_id": "test-session",
        "stop_hook_active": False,
        "transcript_path": str(tpath),
    }

    # When invoking the hook
    proc = _run_hook(hook, payload)

    # Then the hook exits 0 with no block decision
    assert proc.returncode == 0, f"stderr={proc.stderr!r}"
    assert not proc.stdout.strip(), f"unexpected stdout: {proc.stdout!r}"
