"""Characterization tests for enforce_commit_message.py.

Pipes representative payloads through the hook (as a subprocess) and
asserts on exit code and stderr substrings. Like the other hook tests,
exit 0 = allow, exit 2 = block.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from pathlib import Path


def _bash(cmd: str) -> dict[str, Any]:
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": cmd},
    }


HEREDOC_VALID = (
    "git commit -m \"$(cat <<'EOF'\nfeat: add new feature\n\nBody explains why.\nEOF\n)\""
)

HEREDOC_BAD_TYPE = "git commit -m \"$(cat <<'EOF'\nchore: tidy things up\nEOF\n)\""

HEREDOC_UPPERCASE_SUBJECT = "git commit -m \"$(cat <<'EOF'\nfeat: Add new feature\nEOF\n)\""


@dataclass(frozen=True)
class Case:
    """One enforce_commit_message test case."""

    id: str
    payload: dict[str, Any]
    expect_exit: int
    stderr_contains: tuple[str, ...] = ()


CASES: tuple[Case, ...] = (
    # Non-applicable inputs pass through.
    Case(id="empty bash command allowed", payload=_bash(""), expect_exit=0),
    Case(
        id="non-Bash tool ignored",
        payload={"tool_name": "Read", "tool_input": {"file_path": "/proj/x.txt"}},
        expect_exit=0,
    ),
    Case(id="git status allowed", payload=_bash("git status"), expect_exit=0),
    Case(id="git log allowed", payload=_bash("git log -n 5"), expect_exit=0),
    Case(
        id="bare git commit allowed (editor opens)",
        payload=_bash("git commit"),
        expect_exit=0,
    ),
    Case(
        id="git commit -F allowed (file message, cannot inspect)",
        payload=_bash("git commit -F message.txt"),
        expect_exit=0,
    ),
    Case(
        id="git commit --fixup allowed (auto-message)",
        payload=_bash("git commit --fixup HEAD~1"),
        expect_exit=0,
    ),
    Case(
        id="git commit --squash allowed (auto-message)",
        payload=_bash("git commit --squash HEAD~1"),
        expect_exit=0,
    ),
    # Valid conventional commit messages.
    Case(
        id="valid feat allowed",
        payload=_bash('git commit -m "feat: add new endpoint"'),
        expect_exit=0,
    ),
    Case(
        id="valid feat with scope allowed",
        payload=_bash('git commit -m "feat(api): add new endpoint"'),
        expect_exit=0,
    ),
    Case(
        id="valid fix allowed",
        payload=_bash('git commit -m "fix: handle null input"'),
        expect_exit=0,
    ),
    Case(
        id="valid docs allowed",
        payload=_bash('git commit -m "docs: clarify install steps"'),
        expect_exit=0,
    ),
    Case(
        id="valid with PR suffix allowed",
        payload=_bash('git commit -m "feat: distribute as marketplace (#2)"'),
        expect_exit=0,
    ),
    Case(
        id="valid breaking change marker allowed",
        payload=_bash('git commit -m "feat!: drop python 3.13 support"'),
        expect_exit=0,
    ),
    Case(
        id="valid breaking change with scope allowed",
        payload=_bash('git commit -m "feat(api)!: rename endpoint"'),
        expect_exit=0,
    ),
    Case(
        id="valid -am form allowed",
        payload=_bash("git commit -am 'fix: handle null input'"),
        expect_exit=0,
    ),
    Case(
        id="valid --message= form allowed",
        payload=_bash('git commit --message="docs: clarify install"'),
        expect_exit=0,
    ),
    Case(
        id="valid --message space form allowed",
        payload=_bash('git commit --message "ci: fix flaky test"'),
        expect_exit=0,
    ),
    Case(
        id="valid --amend with -m allowed",
        payload=_bash('git commit --amend -m "fix: correct prior commit"'),
        expect_exit=0,
    ),
    Case(
        id="valid with -c prefix allowed",
        payload=_bash("git -c user.email=test@example.com commit -m 'fix: handle null input'"),
        expect_exit=0,
    ),
    Case(
        id="valid heredoc allowed",
        payload=_bash(HEREDOC_VALID),
        expect_exit=0,
    ),
    Case(
        id="two -m args validates first allowed",
        payload=_bash('git commit -m "feat: add foo" -m "Body explains why."'),
        expect_exit=0,
    ),
    # Auto-generated messages skipped.
    Case(
        id="merge auto-message allowed",
        payload=_bash("git commit -m \"Merge branch 'feat' into main\""),
        expect_exit=0,
    ),
    Case(
        id="revert auto-message allowed",
        payload=_bash("git commit -m 'Revert \"feat: bad change\"'"),
        expect_exit=0,
    ),
    Case(
        id="fixup! auto-message allowed",
        payload=_bash('git commit -m "fixup! feat: add foo"'),
        expect_exit=0,
    ),
    Case(
        id="squash! auto-message allowed",
        payload=_bash('git commit -m "squash! feat: add foo"'),
        expect_exit=0,
    ),
    # Block: malformed header.
    Case(
        id="missing type blocked",
        payload=_bash('git commit -m "Add new feature"'),
        expect_exit=2,
        stderr_contains=("BLOCKED", "bad-format"),
    ),
    Case(
        id="missing colon blocked",
        payload=_bash('git commit -m "feat add foo"'),
        expect_exit=2,
        stderr_contains=("bad-format",),
    ),
    Case(
        id="uppercase type blocked",
        payload=_bash('git commit -m "Feat: add foo"'),
        expect_exit=2,
        stderr_contains=("bad-format",),
    ),
    # Block: bad type.
    Case(
        id="chore type blocked",
        payload=_bash('git commit -m "chore: tidy things"'),
        expect_exit=2,
        stderr_contains=("bad-type", "chore"),
    ),
    Case(
        id="wip type blocked",
        payload=_bash('git commit -m "wip: in progress"'),
        expect_exit=2,
        stderr_contains=("bad-type", "wip"),
    ),
    # Block: subject style.
    Case(
        id="uppercase subject blocked",
        payload=_bash('git commit -m "feat: Add new feature"'),
        expect_exit=2,
        stderr_contains=("subject-uppercase",),
    ),
    Case(
        id="trailing period blocked",
        payload=_bash('git commit -m "feat: add new feature."'),
        expect_exit=2,
        stderr_contains=("subject-trailing-period",),
    ),
    # Block: header length.
    Case(
        id="header too long blocked",
        payload=_bash('git commit -m "feat: ' + ("a" * 80) + '"'),
        expect_exit=2,
        stderr_contains=("header-too-long",),
    ),
    # Block: empty subject.
    Case(
        id="empty message blocked",
        payload=_bash('git commit -m ""'),
        expect_exit=2,
        stderr_contains=("empty-subject",),
    ),
    # Block: -am with bad message.
    Case(
        id="bad -am form blocked",
        payload=_bash('git commit -am "added: new things"'),
        expect_exit=2,
        stderr_contains=("bad-type",),
    ),
    # Block: heredoc with bad first line.
    Case(
        id="heredoc bad type blocked",
        payload=_bash(HEREDOC_BAD_TYPE),
        expect_exit=2,
        stderr_contains=("bad-type", "chore"),
    ),
    Case(
        id="heredoc uppercase subject blocked",
        payload=_bash(HEREDOC_UPPERCASE_SUBJECT),
        expect_exit=2,
        stderr_contains=("subject-uppercase",),
    ),
    # Block: --amend with bad new message.
    Case(
        id="--amend with bad message blocked",
        payload=_bash('git commit --amend -m "Bad: format"'),
        expect_exit=2,
    ),
    # Block: non-imperative first word.
    Case(
        id="past tense first word blocked",
        payload=_bash('git commit -m "feat: added new feature"'),
        expect_exit=2,
        stderr_contains=("subject-not-imperative", "added", "add"),
    ),
    Case(
        id="gerund first word blocked",
        payload=_bash('git commit -m "fix: fixing null pointer"'),
        expect_exit=2,
        stderr_contains=("subject-not-imperative", "fixing", "fix"),
    ),
    Case(
        id="third-person first word blocked",
        payload=_bash('git commit -m "build: bumps deps"'),
        expect_exit=2,
        stderr_contains=("subject-not-imperative", "bumps", "bump"),
    ),
    # Allow: imperative root forms of denylisted verbs pass.
    Case(
        id="imperative add allowed",
        payload=_bash('git commit -m "feat: add new feature"'),
        expect_exit=0,
    ),
    Case(
        id="imperative bump allowed",
        payload=_bash('git commit -m "build: bump deps"'),
        expect_exit=0,
    ),
    # Allow: imperatives that happen to end in -ed/-ing/-s pass (not denylisted).
    Case(
        id="release verb allowed",
        payload=_bash('git commit -m "feat: release v1.0"'),
        expect_exit=0,
    ),
    Case(
        id="pass verb allowed",
        payload=_bash('git commit -m "fix: pass context to handler"'),
        expect_exit=0,
    ),
    # Block: trailing whitespace.
    Case(
        id="trailing space blocked",
        payload=_bash('git commit -m "feat: add new feature "'),
        expect_exit=2,
        stderr_contains=("subject-trailing-whitespace",),
    ),
    Case(
        id="trailing tab blocked",
        payload=_bash("git commit -m 'fix: handle null\t'"),
        expect_exit=2,
        stderr_contains=("subject-trailing-whitespace",),
    ),
    # Block: trailing exclamation / question.
    Case(
        id="trailing exclamation blocked",
        payload=_bash('git commit -m "feat: add new feature!"'),
        expect_exit=2,
        stderr_contains=("subject-trailing-punctuation", "!"),
    ),
    Case(
        id="trailing question blocked",
        payload=_bash('git commit -m "fix: handle null?"'),
        expect_exit=2,
        stderr_contains=("subject-trailing-punctuation", "?"),
    ),
    # Block: WIP / Draft markers in subject.
    Case(
        id="lowercase wip marker blocked",
        payload=_bash('git commit -m "feat: wip add new feature"'),
        expect_exit=2,
        stderr_contains=("subject-wip-marker",),
    ),
    Case(
        id="uppercase WIP marker blocked",
        payload=_bash('git commit -m "feat: WIP add new feature"'),
        expect_exit=2,
        stderr_contains=("subject-wip-marker",),
    ),
    Case(
        id="bracketed WIP marker blocked",
        payload=_bash('git commit -m "feat: [WIP] add new feature"'),
        expect_exit=2,
        stderr_contains=("subject-wip-marker",),
    ),
    Case(
        id="lowercase draft marker blocked",
        payload=_bash('git commit -m "feat: draft new feature"'),
        expect_exit=2,
        stderr_contains=("subject-wip-marker",),
    ),
    Case(
        id="parenthesized draft marker blocked",
        payload=_bash('git commit -m "feat: (draft) add new feature"'),
        expect_exit=2,
        stderr_contains=("subject-wip-marker",),
    ),
    Case(
        id="bracketed Draft marker blocked",
        payload=_bash('git commit -m "feat: [Draft] add new feature"'),
        expect_exit=2,
        stderr_contains=("subject-wip-marker",),
    ),
)


@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_enforce_commit_message(case: Case, hooks_dir: Path) -> None:
    """Verify the hook blocks or allows each commit-message pattern."""
    # Given the hook script
    hook = hooks_dir / "enforce_commit_message.py"

    # When invoking the hook with the payload on stdin
    proc = subprocess.run(
        [str(hook)],
        input=json.dumps(case.payload),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    # Then exit code and stderr content match expectations
    diag = f"\n  stderr={proc.stderr!r}\n  stdout={proc.stdout!r}"
    assert proc.returncode == case.expect_exit, f"exit={proc.returncode}{diag}"
    for s in case.stderr_contains:
        assert s in proc.stderr, f"missing {s!r} in stderr{diag}"
    # Every block must include the format-spec footer so the agent can
    # fix the message in one shot rather than chaining rule violations.
    if case.expect_exit == 2:
        assert "Conventional Commits" in proc.stderr, f"missing footer{diag}"
        assert "git-rules" in proc.stderr, f"missing skill pointer{diag}"
