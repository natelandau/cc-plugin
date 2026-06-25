"""Characterization tests for stop/stop_phrase_guard.py.

Calls `evaluate(event, cfg)` directly with a constructed event dict. The
dispatcher pre-parses the transcript and hands the closing assistant text as
`event["assistant_message"]`, so these tests pass that text straight in. The
transcript reconstruction itself (split-across-lines, tool_use-only, message.id
grouping) lives in test_lib_transcript.py; the dispatcher integration test
(test_stop_dispatcher.py) covers the parse + bail path end to end.

Every scenario from the previous subprocess-based suite is preserved: each old
transcript fixture is reduced to the assistant_message it reconstructs to.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parent.parent / "plugins" / "natelandau-toolkit" / "hooks"
for _p in (str(HOOKS), str(HOOKS / "stop")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import stop_phrase_guard  # noqa: E402  # ty: ignore[unresolved-import]


@dataclass(frozen=True)
class _Cfg:
    """Minimal Config stand-in: evaluate only reads project_dir."""

    profile: str = "standard"
    disabled_hooks: frozenset[str] = frozenset()
    project_dir: str | None = None


@dataclass(frozen=True)
class Case:
    id: str
    assistant_message: str
    expect_block: bool = False
    correction_substring: str = ""
    extra_assertions: list[str] = field(default_factory=list)


CASES: tuple[Case, ...] = (
    Case(
        id="clean message: no block",
        assistant_message="Made the changes; tests pass. Ready for your review.",
        expect_block=False,
    ),
    Case(
        id="pre-existing dodge blocked",
        assistant_message="This failure is pre-existing and unrelated to my change.",
        expect_block=True,
        correction_substring="NOTHING IS PRE-EXISTING",
    ),
    Case(
        id="case-insensitive match",
        assistant_message="PRE-EXISTING failure, leaving as-is.",
        expect_block=True,
        correction_substring="NOTHING IS PRE-EXISTING",
    ),
    Case(
        # "pre-existing" with ownership taken (a fix) is not a dodge.
        id="pre-existing mention without inaction: no block",
        assistant_message="I fixed the pre-existing lint error; the suite is green.",
        expect_block=False,
    ),
    Case(
        # Meta-discussion of the rule itself must not trip the rule.
        id="discussing the pre-existing rule: no block",
        assistant_message="The bare `pre-existing` pattern was too broad and matched ordinary prose.",
        expect_block=False,
    ),
    Case(
        id="known limitation dodge blocked",
        assistant_message="This is a known limitation of the parser; not addressing.",
        expect_block=True,
        correction_substring="NO KNOWN LIMITATIONS",
    ),
    Case(
        id="future work dodge blocked",
        assistant_message="Leaving the cleanup as future work.",
        expect_block=True,
        correction_substring="NO KNOWN LIMITATIONS",
    ),
    Case(
        id="should I continue blocked",
        assistant_message="I've finished step 2. Should I continue with step 3?",
        expect_block=True,
        correction_substring="Do not ask",
    ),
    Case(
        id="next session deferral blocked",
        assistant_message="We can wrap this in the next session.",
        expect_block=True,
        correction_substring="next session",
    ),
    Case(
        id="pause here blocked",
        assistant_message="Let me pause here so you can review.",
        expect_block=True,
        correction_substring="Do not pause",
    ),
    Case(
        # The transcript scan walks back past a trailing user entry to the last
        # assistant text; the reconstructed message still carries the violation.
        id="walks back past trailing user entry to find last assistant text",
        assistant_message="This is pre-existing, so I left it untouched.",
        expect_block=True,
        correction_substring="NOTHING IS PRE-EXISTING",
    ),
    Case(
        # Final assistant entry was tool_use only; the reconstructed message is
        # the earlier clean text block.
        id="last assistant entry is tool_use only: skip and check earlier",
        assistant_message="Made the changes; tests pass. Ready for your review.",
        expect_block=False,
    ),
    Case(
        # Real Claude Code shape: one message split across per-block lines. The
        # violation sits in an earlier text block of the same message, so the
        # reconstructed text contains both blocks joined.
        id="message split across lines: earlier text block still scanned",
        assistant_message=(
            "This failure is pre-existing, so I am leaving it untouched.\n"
            "All wrapped up; ready for your review."
        ),
        expect_block=True,
        correction_substring="NOTHING IS PRE-EXISTING",
    ),
    Case(
        # "Final message only" scope: a violation in an earlier message of the
        # same turn is not in the reconstructed closing message, which is clean.
        id="violation in earlier message (different id) is not scanned",
        assistant_message="All done; tests pass. Ready for review.",
        expect_block=False,
    ),
    Case(
        # Empty transcript / missing transcript_path both reduce to no message.
        id="empty message (empty or missing transcript): no block",
        assistant_message="",
        expect_block=False,
    ),
    Case(
        id="multiple violations: first match wins (ordering)",
        assistant_message="This is pre-existing, not fixing it. Should I continue?",
        expect_block=True,
        correction_substring="NOTHING IS PRE-EXISTING",
    ),
)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_stop_phrase_guard(case: Case) -> None:
    """Verify evaluate blocks violations and passes clean messages through."""
    # Given an event carrying the closing assistant message
    event = {"assistant_message": case.assistant_message}

    # When evaluate runs against the default config
    decision = stop_phrase_guard.evaluate(event, _Cfg())

    # Then a blocking decision is returned for a violation, else None
    if case.expect_block:
        assert decision is not None
        assert decision.block
        assert decision.reason.startswith("STOP HOOK VIOLATION:"), decision.reason
        if case.correction_substring:
            assert case.correction_substring.lower() in decision.reason.lower()
    else:
        assert decision is None


def test_project_violation_blocks(tmp_path: Path) -> None:
    """Verify a project-supplied violation phrase blocks the Stop turn."""
    # Given a project rules file adding a custom violation phrase
    rules_dir = tmp_path / ".claude" / "natelandau-toolkit"
    rules_dir.mkdir(parents=True, exist_ok=True)
    (rules_dir / "stop_phrase_guard.rules.toml").write_text(
        '[[violation]]\nid = "no-frobnicate"\nreason = "do not frobnicate"\npattern = "frobnicate"\n',
        encoding="utf-8",
    )
    event = {"assistant_message": "I will now frobnicate the widget."}

    # When evaluate runs with the project dir pointing at those rules
    decision = stop_phrase_guard.evaluate(event, _Cfg(project_dir=str(tmp_path)))

    # Then the project reason drives the block
    assert decision is not None
    assert decision.block
    assert "do not frobnicate" in decision.reason
