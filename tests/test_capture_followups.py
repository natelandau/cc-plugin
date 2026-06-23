"""Characterization tests for capture_followups.py.

Builds fake JSONL transcripts in a tmp dir, pipes Stop hook payloads
through the hook script, and asserts on exit code and (when blocking) the
JSON decision shape and content. Mirrors test_stop_phrase_guard.py: both
are Stop hooks reading `transcript_path`.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from pathlib import Path

BACKLOG_NAME = "BACKLOG.md"


def _assistant_block_entry(block: dict[str, Any], message_id: str) -> dict[str, Any]:
    """Build one JSONL line carrying a single content block."""
    return {
        "type": "assistant",
        "message": {"id": message_id, "role": "assistant", "content": [block]},
    }


def _assistant_text_entry(text: str, message_id: str = "msg-default") -> dict[str, Any]:
    """Build a single-text-block assistant line (the common case)."""
    return _assistant_block_entry({"type": "text", "text": text}, message_id)


def _backlog_write_entry(
    file_path: str = f".agent/{BACKLOG_NAME}", message_id: str = "msg-write"
) -> dict[str, Any]:
    """Build an assistant line writing to the backlog file via the Write tool."""
    return _assistant_block_entry(
        {"type": "tool_use", "name": "Write", "input": {"file_path": file_path}},
        message_id,
    )


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
    omit_transcript_path: bool = False


CASES: tuple[Case, ...] = (
    Case(
        id="clean message: no block",
        entries=[_assistant_text_entry("Made the changes; tests pass. Ready for your review.")],
        expect_block=False,
    ),
    Case(
        id="out of scope deferral blocked",
        entries=[
            _assistant_text_entry(
                "I added the auth check. Rate limiting is out of scope for this change."
            )
        ],
        expect_block=True,
    ),
    Case(
        id="follow-up PR deferral blocked",
        entries=[
            _assistant_text_entry("Done. The caching rewrite is best left for a follow-up PR.")
        ],
        expect_block=True,
    ),
    Case(
        id="TODO left blocked",
        entries=[
            _assistant_text_entry("Shipped the fix. I left a TODO where the retry logic goes.")
        ],
        expect_block=True,
    ),
    Case(
        id="separate change deferral blocked",
        entries=[
            _assistant_text_entry("Migrated the model. The data backfill should be its own PR.")
        ],
        expect_block=True,
    ),
    Case(
        id="future improvement blocked",
        entries=[
            _assistant_text_entry("Working now. Memoizing the parser is a future optimization.")
        ],
        expect_block=True,
    ),
    Case(
        id="handle separately blocked",
        entries=[
            _assistant_text_entry("Fixed the crash. We can address the logging gaps separately.")
        ],
        expect_block=True,
    ),
    Case(
        # Standalone "deferred" (no trailing object) must still fire.
        id="standalone deferred blocked",
        entries=[_assistant_text_entry("Implemented the core path. The cleanup is deferred.")],
        expect_block=True,
    ),
    Case(
        id="for now deferral blocked",
        entries=[
            _assistant_text_entry("Shipped the fix. I'll leave the broader refactor for now.")
        ],
        expect_block=True,
    ),
    Case(
        id="revisit deferral blocked",
        entries=[
            _assistant_text_entry("Working. We can revisit the caching strategy after launch.")
        ],
        expect_block=True,
    ),
    Case(
        id="not addressing deferral blocked",
        entries=[
            _assistant_text_entry("Patched the parser. I'm not addressing the logging gaps here.")
        ],
        expect_block=True,
    ),
    Case(
        # Precision: a follow-up *question* is not a unit of deferred work.
        id="benign follow-up question: no block",
        entries=[_assistant_text_entry("Here is the result. One follow-up question: which env?")],
        expect_block=False,
    ),
    Case(
        # Precision: "for now" in ordinary prose (not a deferral verb) is fine.
        id="benign for-now usage: no block",
        entries=[_assistant_text_entry("For now the tests all pass and the build is green.")],
        expect_block=False,
    ),
    Case(
        # Precision: discussing scope generally is not naming out-of-scope work.
        id="benign scope mention: no block",
        entries=[_assistant_text_entry("I widened the scope of the test to cover both branches.")],
        expect_block=False,
    ),
    Case(
        # The model captured the item inline this turn: suppress the block.
        id="backlog written this turn suppresses block",
        entries=[
            _backlog_write_entry(),
            _assistant_text_entry(
                "Recorded the rate-limiting work (out of scope here) in the backlog."
            ),
        ],
        expect_block=False,
    ),
    Case(
        # A backlog write in a PRIOR turn must not suppress a new deferral.
        id="backlog write before last user does not suppress",
        entries=[
            _backlog_write_entry(),
            _user_entry("now do the next thing"),
            _assistant_text_entry("Done. The polish pass is out of scope for now."),
        ],
        expect_block=True,
    ),
    Case(
        id="stop_hook_active=true bypasses even on deferral",
        entries=[_assistant_text_entry("Rate limiting is out of scope for this change.")],
        stop_hook_active=True,
        expect_block=False,
    ),
    Case(
        id="empty transcript file: no block",
        entries=[],
        expect_block=False,
    ),
    Case(
        id="missing transcript_path: no block",
        entries=[_assistant_text_entry("This is out of scope.")],
        expect_block=False,
        omit_transcript_path=True,
    ),
)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_capture_followups(case: Case, tmp_path: Path, hooks_dir: Path) -> None:
    """Verify the hook blocks uncaptured deferrals and passes clean turns through."""
    # Given a transcript file (or no transcript_path) and a Stop payload
    hook = hooks_dir / "capture_followups.py"
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
        assert reason.startswith("DEFERRED WORK:"), reason
        assert BACKLOG_NAME in reason
    else:
        assert not proc.stdout.strip(), f"unexpected stdout: {proc.stdout!r}"


def test_capture_followups_skips_malformed_lines(tmp_path: Path, hooks_dir: Path) -> None:
    """Verify the hook ignores non-JSON transcript lines and processes valid ones."""
    # Given a transcript with one malformed line followed by a clean assistant turn
    hook = hooks_dir / "capture_followups.py"
    tpath = tmp_path / "transcript.jsonl"
    tpath.write_text(
        "this is not json\n" + json.dumps(_assistant_text_entry("All good, tests pass.")) + "\n",
        encoding="utf-8",
    )
    payload = {
        "hook_event_name": "Stop",
        "stop_hook_active": False,
        "transcript_path": str(tpath),
    }

    # When invoking the hook
    proc = _run_hook(hook, payload)

    # Then the hook exits 0 with no block decision
    assert proc.returncode == 0, f"stderr={proc.stderr!r}"
    assert not proc.stdout.strip(), f"unexpected stdout: {proc.stdout!r}"


def test_project_trigger_blocks(hooks_dir: Path, tmp_path: Path) -> None:
    """Verify a project-supplied trigger phrase blocks the Stop turn."""
    # Given a transcript whose closing message contains a custom phrase
    transcript = _make_transcript(
        tmp_path, [_assistant_text_entry("I will move the widget polish to the icebox.")]
    )
    # Given a project rules file adding that phrase as a trigger
    rules_dir = tmp_path / ".claude" / "natelandau-toolkit"
    rules_dir.mkdir(parents=True, exist_ok=True)
    (rules_dir / "capture_followups.rules.toml").write_text(
        '[[trigger]]\nid = "icebox"\nreason = "You moved work to the icebox."\npattern = "icebox"\n',
        encoding="utf-8",
    )
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path)
    payload = {"hook_event_name": "Stop", "transcript_path": str(transcript)}

    # When the Stop hook runs
    proc = subprocess.run(
        [str(hooks_dir / "capture_followups.py")],
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
    assert "icebox" in decision["reason"]
