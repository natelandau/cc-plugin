"""Characterization tests for stop_phrase_guard.py.

Builds fake JSONL transcripts in a tmp dir, pipes Stop hook payloads
through the hook script, asserts on exit code and (when blocking) the
JSON decision shape and content.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from pathlib import Path


def _assistant_block_entry(block: dict[str, Any], message_id: str) -> dict[str, Any]:
    """Build one JSONL line carrying a single content block.

    Mirrors how Claude Code records transcripts: each content block of a
    message is its own `type == "assistant"` line, all sharing one
    `message.id`.
    """
    return {
        "type": "assistant",
        "message": {"id": message_id, "role": "assistant", "content": [block]},
    }


def _assistant_text_entry(text: str, message_id: str = "msg-default") -> dict[str, Any]:
    """Build a single-text-block assistant line (the common case)."""
    return _assistant_block_entry({"type": "text", "text": text}, message_id)


def _assistant_message(blocks: list[dict[str, Any]], message_id: str) -> list[dict[str, Any]]:
    """Build the per-block JSONL lines for one assistant message.

    Returns one entry per block, all sharing `message_id`, so tests can
    reproduce a message split across multiple transcript lines.
    """
    return [_assistant_block_entry(block, message_id) for block in blocks]


def _assistant_tool_use_entry(message_id: str = "msg-tool") -> dict[str, Any]:
    """Build an assistant line that carries only a tool_use block (no text)."""
    return _assistant_block_entry(
        {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}, message_id
    )


def _tool_result_entry() -> dict[str, Any]:
    """Build a tool-result user line (list content, not a human message)."""
    return {
        "type": "user",
        "message": {"role": "user", "content": [{"type": "tool_result", "content": "ok"}]},
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
        # "pre-existing" with ownership taken (a fix) is not a dodge.
        id="pre-existing mention without inaction: no block",
        entries=[_assistant_text_entry("I fixed the pre-existing lint error; the suite is green.")],
        expect_block=False,
    ),
    Case(
        # Meta-discussion of the rule itself must not trip the rule.
        id="discussing the pre-existing rule: no block",
        entries=[
            _assistant_text_entry(
                "The bare `pre-existing` pattern was too broad and matched ordinary prose."
            )
        ],
        expect_block=False,
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
            _assistant_text_entry("This is pre-existing, so I left it untouched."),
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
        # Real Claude Code shape: one message split across per-block lines.
        # The violation sits in an earlier text block; reading only the
        # final block would miss it.
        id="message split across lines: earlier text block still scanned",
        entries=_assistant_message(
            [
                {"type": "thinking", "thinking": "internal reasoning"},
                {
                    "type": "text",
                    "text": "This failure is pre-existing, so I am leaving it untouched.",
                },
                {"type": "text", "text": "All wrapped up; ready for your review."},
            ],
            message_id="msg-split",
        ),
        expect_block=True,
        correction_substring="NOTHING IS PRE-EXISTING",
    ),
    Case(
        # "Final message only" scope: a violation in an earlier message of
        # the same turn (before a tool call) is not re-flagged once a clean
        # closing message follows.
        id="violation in earlier message (different id) is not scanned",
        entries=[
            *_assistant_message(
                [
                    {"type": "text", "text": "This failure is pre-existing, leaving it untouched."},
                    {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}},
                ],
                message_id="msg-1",
            ),
            _tool_result_entry(),
            *_assistant_message(
                [{"type": "text", "text": "All done; tests pass. Ready for review."}],
                message_id="msg-2",
            ),
        ],
        expect_block=False,
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
        entries=[_assistant_text_entry("This is pre-existing, not fixing it. Should I continue?")],
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


def test_project_violation_blocks(hooks_dir: Path, tmp_path: Path) -> None:
    """Verify a project-supplied violation phrase blocks the Stop turn."""
    # Given a transcript whose final assistant message contains a custom phrase
    transcript = _make_transcript(
        tmp_path, [_assistant_text_entry("I will now frobnicate the widget.")]
    )
    # Given a project rules file adding that phrase as a violation
    rules_dir = tmp_path / ".claude" / "natelandau-toolkit"
    rules_dir.mkdir(parents=True, exist_ok=True)
    (rules_dir / "stop_phrase_guard.rules.toml").write_text(
        '[[violation]]\nid = "no-frobnicate"\nreason = "do not frobnicate"\npattern = "frobnicate"\n',
        encoding="utf-8",
    )
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path)
    payload = {"hook_event_name": "Stop", "transcript_path": str(transcript)}

    # When the Stop hook runs
    proc = subprocess.run(
        [str(hooks_dir / "stop_phrase_guard.py")],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
        env=env,
    )

    # Then it emits a block decision (exit 0, JSON on stdout) with the project reason
    assert proc.returncode == 0, f"stderr={proc.stderr!r}"
    decision = json.loads(proc.stdout)
    assert decision["decision"] == "block"
    assert "do not frobnicate" in decision["reason"]
