"""Characterization tests for stop/capture_followups.py.

Calls `evaluate(event, cfg)` directly with a constructed event dict. The
dispatcher pre-parses the transcript and hands the closing assistant text as
`event["assistant_message"]` and the turn's parsed entries as
`event["entries"]`, so these tests build both directly. The entry dicts mirror
the shape `lib.transcript.file_written_since_last_user` expects (the same shape
test_lib_transcript.py uses), so the self-suppression path is exercised without
a real transcript file.

Every scenario from the previous subprocess-based suite is preserved.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

HOOKS = Path(__file__).resolve().parent.parent / "plugins" / "natelandau-toolkit" / "hooks"
for _p in (str(HOOKS), str(HOOKS / "stop")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import capture_followups  # noqa: E402  # ty: ignore[unresolved-import]

BACKLOG_NAME = "BACKLOG.md"


@dataclass(frozen=True)
class _Cfg:
    """Minimal Config stand-in: evaluate reads project_dir and option()."""

    profile: str = "standard"
    disabled_hooks: frozenset[str] = frozenset()
    project_dir: str | None = None
    hook_options: dict[str, dict[str, str]] = field(default_factory=dict)

    def option(self, hook_id: str, key: str, default: str) -> str:
        return self.hook_options.get(hook_id, {}).get(key, default)


def _backlog_write_entry(
    file_path: str = f".agent/{BACKLOG_NAME}", message_id: str = "msg-write"
) -> dict[str, Any]:
    """Build an assistant line writing the backlog via the Write tool."""
    return {
        "type": "assistant",
        "message": {
            "id": message_id,
            "role": "assistant",
            "content": [{"type": "tool_use", "name": "Write", "input": {"file_path": file_path}}],
        },
    }


def _user_entry(text: str) -> dict[str, Any]:
    return {"type": "user", "message": {"role": "user", "content": text}}


@dataclass(frozen=True)
class Case:
    id: str
    assistant_message: str
    entries: list[dict[str, Any]] = field(default_factory=list)
    expect_block: bool = False


CASES: tuple[Case, ...] = (
    Case(
        id="clean message: no block",
        assistant_message="Made the changes; tests pass. Ready for your review.",
        expect_block=False,
    ),
    Case(
        id="out of scope deferral blocked",
        assistant_message="I added the auth check. Rate limiting is out of scope for this change.",
        expect_block=True,
    ),
    Case(
        id="follow-up PR deferral blocked",
        assistant_message="Done. The caching rewrite is best left for a follow-up PR.",
        expect_block=True,
    ),
    Case(
        id="TODO left blocked",
        assistant_message="Shipped the fix. I left a TODO where the retry logic goes.",
        expect_block=True,
    ),
    Case(
        id="separate change deferral blocked",
        assistant_message="Migrated the model. The data backfill should be its own PR.",
        expect_block=True,
    ),
    Case(
        id="future improvement blocked",
        assistant_message="Working now. Memoizing the parser is a future optimization.",
        expect_block=True,
    ),
    Case(
        id="handle separately blocked",
        assistant_message="Fixed the crash. We can address the logging gaps separately.",
        expect_block=True,
    ),
    Case(
        # Standalone "deferred" (no trailing object) must still fire.
        id="standalone deferred blocked",
        assistant_message="Implemented the core path. The cleanup is deferred.",
        expect_block=True,
    ),
    Case(
        id="for now deferral blocked",
        assistant_message="Shipped the fix. I'll leave the broader refactor for now.",
        expect_block=True,
    ),
    Case(
        id="revisit deferral blocked",
        assistant_message="Working. We can revisit the caching strategy after launch.",
        expect_block=True,
    ),
    Case(
        id="not addressing deferral blocked",
        assistant_message="Patched the parser. I'm not addressing the logging gaps here.",
        expect_block=True,
    ),
    Case(
        # Precision: a follow-up *question* is not a unit of deferred work.
        id="benign follow-up question: no block",
        assistant_message="Here is the result. One follow-up question: which env?",
        expect_block=False,
    ),
    Case(
        # Precision: "for now" in ordinary prose (not a deferral verb) is fine.
        id="benign for-now usage: no block",
        assistant_message="For now the tests all pass and the build is green.",
        expect_block=False,
    ),
    Case(
        # Precision: discussing scope generally is not naming out-of-scope work.
        id="benign scope mention: no block",
        assistant_message="I widened the scope of the test to cover both branches.",
        expect_block=False,
    ),
    Case(
        # The model captured the item inline this turn: suppress the block.
        id="backlog written this turn suppresses block",
        assistant_message="Recorded the rate-limiting work (out of scope here) in the backlog.",
        entries=[_backlog_write_entry()],
        expect_block=False,
    ),
    Case(
        # A backlog write in a PRIOR turn must not suppress a new deferral.
        id="backlog write before last user does not suppress",
        assistant_message="Done. The polish pass is out of scope for now.",
        entries=[_backlog_write_entry(), _user_entry("now do the next thing")],
        expect_block=True,
    ),
    Case(
        # Empty transcript / missing transcript_path both reduce to no message.
        id="empty message (empty or missing transcript): no block",
        assistant_message="",
        expect_block=False,
    ),
)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_capture_followups(case: Case) -> None:
    """Verify evaluate blocks uncaptured deferrals and passes clean turns through."""
    # Given an event with the closing message and this turn's entries
    event = {"assistant_message": case.assistant_message, "entries": case.entries}

    # When evaluate runs against the default config
    decision = capture_followups.evaluate(event, _Cfg())

    # Then a blocking decision is returned for an uncaptured deferral, else None
    if case.expect_block:
        assert decision is not None
        assert decision.block
        assert decision.reason.startswith("DEFERRED WORK:"), decision.reason
        assert BACKLOG_NAME in decision.reason
    else:
        assert decision is None


def test_project_trigger_blocks(tmp_path: Path) -> None:
    """Verify a project-supplied trigger phrase blocks the Stop turn."""
    # Given a project rules file adding a custom trigger phrase
    rules_dir = tmp_path / ".claude" / "natelandau-toolkit"
    rules_dir.mkdir(parents=True, exist_ok=True)
    (rules_dir / "capture_followups.rules.toml").write_text(
        '[[trigger]]\nid = "icebox"\nreason = "You moved work to the icebox."\npattern = "icebox"\n',
        encoding="utf-8",
    )
    event = {
        "assistant_message": "I will move the widget polish to the icebox.",
        "entries": [],
    }

    # When evaluate runs with the project dir pointing at those rules
    decision = capture_followups.evaluate(event, _Cfg(project_dir=str(tmp_path)))

    # Then the project reason drives the block
    assert decision is not None
    assert decision.block
    assert "icebox" in decision.reason
