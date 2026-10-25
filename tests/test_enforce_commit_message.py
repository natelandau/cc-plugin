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

from tests._env import clean_environ, exempt_env
from tests._helpers import bash_payload as _bash

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path


HEREDOC_VALID = (
    "git commit -m \"$(cat <<'EOF'\nfeat: add new feature\n\nBody explains why.\nEOF\n)\""
)

HEREDOC_BAD_TYPE = "git commit -m \"$(cat <<'EOF'\ntask: tidy things up\nEOF\n)\""

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
        id="unknown type blocked",
        payload=_bash('git commit -m "task: tidy things"'),
        expect_exit=2,
        stderr_contains=("bad-type", "task"),
    ),
    # Allow: commitlint config-conventional types beyond the classic Angular set.
    Case(
        id="chore type allowed by default",
        payload=_bash('git commit -m "chore: tidy things"'),
        expect_exit=0,
    ),
    Case(
        id="revert type allowed by default",
        payload=_bash('git commit -m "revert: undo the cache change"'),
        expect_exit=0,
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
    # Subject length: the default limit is 100 characters for the whole first line.
    Case(
        id="subject of 90 chars allowed by default",
        payload=_bash('git commit -m "feat: ' + ("a" * 84) + '"'),
        expect_exit=0,
    ),
    Case(
        id="subject over 100 chars blocked",
        payload=_bash('git commit -m "feat: ' + ("a" * 95) + '"'),
        expect_exit=2,
        stderr_contains=("subject-too-long", "101 chars"),
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
        stderr_contains=("bad-type", "task"),
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
    # Allow: the imperative check is off by default (see CONFIGURED_CASES).
    Case(
        id="past tense first word allowed by default",
        payload=_bash('git commit -m "feat: added new feature"'),
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
    # gh pr: non-validated subcommands and missing-title forms pass through.
    Case(id="gh pr view allowed", payload=_bash("gh pr view 23"), expect_exit=0),
    Case(id="gh pr list allowed", payload=_bash("gh pr list"), expect_exit=0),
    Case(
        id="gh pr create no title allowed (editor opens)",
        payload=_bash("gh pr create"),
        expect_exit=0,
    ),
    Case(
        id="gh pr create --fill allowed (title from commits)",
        payload=_bash("gh pr create --fill"),
        expect_exit=0,
    ),
    Case(
        id="gh pr edit body only allowed (no title)",
        payload=_bash('gh pr edit 23 --body "Some description"'),
        expect_exit=0,
    ),
    Case(
        id="gh pr merge no subject allowed (inherits PR title)",
        payload=_bash("gh pr merge 23 --squash"),
        expect_exit=0,
    ),
    # gh pr: valid conventional titles pass.
    Case(
        id="gh pr create valid feat allowed",
        payload=_bash('gh pr create --title "feat: add new endpoint"'),
        expect_exit=0,
    ),
    Case(
        id="gh pr create valid -t short form allowed",
        payload=_bash('gh pr create -t "fix: handle null input"'),
        expect_exit=0,
    ),
    Case(
        id="gh pr create valid --title= equals form allowed",
        payload=_bash('gh pr create --title="docs: clarify install"'),
        expect_exit=0,
    ),
    Case(
        id="gh pr edit valid title allowed",
        payload=_bash('gh pr edit 23 --title "feat(api): add new endpoint"'),
        expect_exit=0,
    ),
    Case(
        id="gh pr merge valid --subject allowed",
        payload=_bash('gh pr merge 23 --squash --subject "feat: ship the thing"'),
        expect_exit=0,
    ),
    Case(
        id="gh pr merge valid -t short subject allowed",
        payload=_bash('gh pr merge 23 -t "fix: correct merge logic"'),
        expect_exit=0,
    ),
    # gh pr: malformed titles block with the same rules as commits.
    Case(
        id="gh pr create missing type blocked",
        payload=_bash('gh pr create --title "Add new feature"'),
        expect_exit=2,
        stderr_contains=("BLOCKED", "bad-format"),
    ),
    Case(
        id="gh pr create bad type blocked",
        payload=_bash('gh pr create --title "task: tidy things"'),
        expect_exit=2,
        stderr_contains=("bad-type", "task"),
    ),
    Case(
        id="gh pr create uppercase subject blocked",
        payload=_bash('gh pr create -t "feat: Add new feature"'),
        expect_exit=2,
        stderr_contains=("subject-uppercase",),
    ),
    Case(
        id="gh pr edit bad type blocked",
        payload=_bash('gh pr edit 23 --title "wip: in progress"'),
        expect_exit=2,
        stderr_contains=("bad-type", "wip"),
    ),
    Case(
        id="gh pr merge malformed subject blocked",
        payload=_bash('gh pr merge 23 --subject "Ship it."'),
        expect_exit=2,
        stderr_contains=("bad-format",),
    ),
    Case(
        id="gh pr create empty title blocked names PR title",
        payload=_bash('gh pr create --title ""'),
        expect_exit=2,
        stderr_contains=("empty-subject", "PR title"),
    ),
    # gh pr: --title takes precedence over --fill, so it is validated.
    Case(
        id="gh pr create --fill with bad --title blocked",
        payload=_bash('gh pr create --fill --title "Add new feature"'),
        expect_exit=2,
        stderr_contains=("bad-format",),
    ),
    # Precedence: a chained commit+PR validates only the commit (existing
    # path wins); the PR title is intentionally not inspected here.
    Case(
        id="chained git commit and gh pr validates commit only",
        payload=_bash('git commit -m "feat: add foo" && gh pr create --title "Bad title"'),
        expect_exit=0,
    ),
    # Tokenization hardening (§1.5): the -m value must be extracted from
    # combined, multi-flag, zero-space, and `--message=` forms. Each uses a
    # subject that violates (uppercase) so a block proves extraction fired.
    Case(
        id="git commit -am extracts message (combined flags)",
        payload=_bash('git commit -am "feat: Add thing"'),
        expect_exit=2,
        stderr_contains=("subject-uppercase",),
    ),
    Case(
        id="git commit -sm extracts message (signoff + message)",
        payload=_bash('git commit -sm "feat: Add thing"'),
        expect_exit=2,
        stderr_contains=("subject-uppercase",),
    ),
    Case(
        id="git commit -m with no space extracts message",
        payload=_bash('git commit -m"feat: Add thing"'),
        expect_exit=2,
        stderr_contains=("subject-uppercase",),
    ),
    Case(
        id="git commit --message= extracts message",
        payload=_bash('git commit --message="feat: Add thing"'),
        expect_exit=2,
        stderr_contains=("subject-uppercase",),
    ),
)


@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_enforce_commit_message(
    case: Case, run_pretooluse: Callable[[dict[str, Any]], subprocess.CompletedProcess[str]]
) -> None:
    """Verify the hook blocks or allows each commit-message pattern."""
    # When invoking the hook with the payload on stdin
    proc = run_pretooluse(case.payload)

    # Then exit code and stderr content match expectations
    diag = f"\n  stderr={proc.stderr!r}\n  stdout={proc.stdout!r}"
    assert proc.returncode == case.expect_exit, f"exit={proc.returncode}{diag}"
    for s in case.stderr_contains:
        assert s in proc.stderr, f"missing {s!r} in stderr{diag}"
    # Every block must include the active-rules summary so the agent can
    # fix the message in one shot rather than chaining rule violations.
    if case.expect_exit == 2:
        assert "Active rules ([hooks.commit-message]" in proc.stderr, f"missing summary{diag}"


def test_block_message_bracket_slug_is_hook_id(
    run_pretooluse: Callable[[dict[str, Any]], subprocess.CompletedProcess[str]],
) -> None:
    """The bracket slug is the hook id; the matched rule id rides in the message."""
    proc = run_pretooluse(_bash('git commit -m "not a conventional message"'))
    assert proc.returncode == 2, f"stderr={proc.stderr!r}"
    assert "BLOCKED [commit-message]:" in proc.stderr
    assert "'bad-format'" in proc.stderr


# === Exempt-path carve-out ==================================================

# A subject the conventions reject on three counts (capitalized, past tense,
# trailing period), so a pass-through can only come from the carve-out.
BAD_SUBJECT = "Reorganized the notes."


def _run_with_exempt(
    hooks_dir: Path, payload: dict[str, Any], exempt: str, home: str
) -> subprocess.CompletedProcess[str]:
    """Pipe `payload` through the PreToolUse dispatcher with `exempt` declared an exempt root.

    `home` pins the global config layer and CLAUDE_PROJECT_DIR is dropped, so
    neither a developer's own toolkit config nor the checkout the suite runs
    from can decide whether the hook fires.
    """
    env: dict[str, str] = {**clean_environ(), **exempt_env(exempt), "HOME": home}
    env.pop("CLAUDE_PROJECT_DIR", None)
    return subprocess.run(
        [str(hooks_dir / "pretooluse.py")],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
        env=env,
    )


@pytest.mark.parametrize(
    ("template", "case"),
    [
        ('git -C {root} commit -m "{subject}"', "git -C into the exempt tree"),
        ('cd {root} && git commit -m "{subject}"', "cd into the exempt tree"),
        ('gh pr create -t "{subject}"', "gh pr create from an exempt cwd"),
    ],
)
def test_exempt_commands_skip_the_conventions(
    repos: Mapping[str, str],
    hooks_dir: Path,
    empty_home: str,
    template: str,
    case: str,
) -> None:
    """Verify a non-conventional subject aimed at an exempt tree is allowed."""
    # Given a command carrying a subject the conventions would reject, in an
    # exempt tree on a feature branch so branch-protection cannot block first
    # and mask whether the hook under test allowed it
    root = repos["feat"]
    payload = {**_bash(template.format(root=root, subject=BAD_SUBJECT)), "cwd": root}

    # When invoking the hook with that repo declared an exempt root
    proc = _run_with_exempt(hooks_dir, payload, root, empty_home)

    # Then it passes through
    assert proc.returncode == 0, f"{case}: stderr={proc.stderr!r}"


def test_commit_outside_an_exempt_tree_still_enforced(
    repos: Mapping[str, str], hooks_dir: Path, empty_home: str
) -> None:
    """Verify the conventions still apply to a repo no exempt root contains."""
    # Given a non-conventional commit aimed at a repo outside every exempt root
    command = f'git commit -m "{BAD_SUBJECT}"'
    payload = {**_bash(command), "cwd": repos["outside"]}

    # When invoking the hook with the exempt root pointed elsewhere
    proc = _run_with_exempt(hooks_dir, payload, repos["feat"], empty_home)

    # Then the message is still blocked
    assert proc.returncode == 2, f"stderr={proc.stderr!r}"
    assert "BLOCKED [commit-message]:" in proc.stderr


# === Configured rules =======================================================


@dataclass(frozen=True)
class ConfiguredCase:
    """One enforce_commit_message case run under a `[hooks.commit-message]` table."""

    id: str
    options: str
    command: str
    expect_exit: int
    stderr_contains: tuple[str, ...] = ()


LONG_BODY = "This body line runs well past the twenty character limit."
URL_LINE = "https://example.com/a/very/long/path/that/cannot/be/wrapped"
TRAILER = "Signed-off-by: A Contributor With A Long Name <someone@example.com>"

CONFIGURED_CASES: tuple[ConfiguredCase, ...] = (
    # force_imperative
    ConfiguredCase(
        id="force_imperative blocks past tense",
        options="force_imperative = true",
        command='git commit -m "feat: added new feature"',
        expect_exit=2,
        stderr_contains=("subject-not-imperative", "added", "'add'"),
    ),
    ConfiguredCase(
        id="force_imperative blocks gerund",
        options="force_imperative = true",
        command='git commit -m "fix: fixing null pointer"',
        expect_exit=2,
        stderr_contains=("subject-not-imperative", "fixing", "'fix'"),
    ),
    ConfiguredCase(
        id="force_imperative blocks third person",
        options="force_imperative = true",
        command='git commit -m "build: bumps deps"',
        expect_exit=2,
        stderr_contains=("subject-not-imperative", "bumps", "'bump'"),
    ),
    ConfiguredCase(
        id="force_imperative allows imperatives ending in -s",
        options="force_imperative = true",
        command='git commit -m "fix: pass context to handler"',
        expect_exit=0,
    ),
    ConfiguredCase(
        id="force_imperative blocks a denied non-verb",
        options="force_imperative = true",
        command='git commit -m "feat(avatar): user-uploaded avatars"',
        expect_exit=2,
        stderr_contains=("subject-not-imperative", "'user' is not a verb"),
    ),
    ConfiguredCase(
        id="force_imperative applies to PR titles",
        options="force_imperative = true",
        command='gh pr create --title "feat: added new feature"',
        expect_exit=2,
        stderr_contains=("subject-not-imperative",),
    ),
    # allowed types and required scope
    ConfiguredCase(
        id="types restricts the allowed list",
        options='types = ["feat"]',
        command='git commit -m "fix: handle null input"',
        expect_exit=2,
        stderr_contains=("bad-type", "use one of: feat"),
    ),
    ConfiguredCase(
        id="require_scope blocks a missing scope",
        options="require_scope = true",
        command='git commit -m "feat: add endpoint"',
        expect_exit=2,
        stderr_contains=("missing-scope", "<scope> required"),
    ),
    ConfiguredCase(
        id="require_scope allows a scoped subject",
        options="require_scope = true",
        command='git commit -m "feat(api): add endpoint"',
        expect_exit=0,
    ),
    # max_subject_length
    ConfiguredCase(
        id="max_subject_length 0 disables the limit",
        options="max_subject_length = 0",
        command='git commit -m "feat: ' + ("a" * 200) + '"',
        expect_exit=0,
    ),
    ConfiguredCase(
        id="max_subject_length tightens the limit and the summary",
        options="max_subject_length = 20",
        command='git commit -m "feat: add a longer subject"',
        expect_exit=2,
        stderr_contains=("subject-too-long", "first line <= 20 chars"),
    ),
    # format, subject_case, punctuation, WIP
    ConfiguredCase(
        id="format none still applies subject_case",
        options='format = "none"',
        command='git commit -m "Add new feature"',
        expect_exit=2,
        stderr_contains=("subject-uppercase",),
    ),
    ConfiguredCase(
        id="format none with subject_case any allows prose",
        options='format = "none"\nsubject_case = "any"',
        command='git commit -m "Add new feature"',
        expect_exit=0,
    ),
    ConfiguredCase(
        id="format none still checks trailing punctuation",
        options='format = "none"\nsubject_case = "any"',
        command='git commit -m "Add new feature."',
        expect_exit=2,
        stderr_contains=("subject-trailing-period",),
    ),
    ConfiguredCase(
        id="subject_case any allows an uppercase subject",
        options='subject_case = "any"',
        command='git commit -m "feat: Add thing"',
        expect_exit=0,
    ),
    ConfiguredCase(
        id="forbid_trailing_punctuation false allows a period",
        options="forbid_trailing_punctuation = false",
        command='git commit -m "feat: add thing."',
        expect_exit=0,
    ),
    ConfiguredCase(
        id="trailing whitespace stays blocked without punctuation rule",
        options="forbid_trailing_punctuation = false",
        command='git commit -m "feat: add thing "',
        expect_exit=2,
        stderr_contains=("subject-trailing-whitespace",),
    ),
    ConfiguredCase(
        id="forbid_wip_subject false allows a WIP marker",
        options="forbid_wip_subject = false",
        command='git commit -m "feat: wip add thing"',
        expect_exit=0,
    ),
    # max_body_line_length
    ConfiguredCase(
        id="max_body_line_length blocks a long body line",
        options="max_body_line_length = 20",
        command=f'git commit -m "feat: add thing" -m "{LONG_BODY}"',
        expect_exit=2,
        stderr_contains=("body-line-too-long", "must be <= 20"),
    ),
    ConfiguredCase(
        id="max_body_line_length checks a heredoc body",
        options="max_body_line_length = 20",
        command=f"git commit -m \"$(cat <<'EOF'\nfeat: add thing\n\n{LONG_BODY}\nEOF\n)\"",
        expect_exit=2,
        stderr_contains=("body-line-too-long",),
    ),
    ConfiguredCase(
        id="max_body_line_length exempts a URL line",
        options="max_body_line_length = 20",
        command=f'git commit -m "feat: add thing" -m "{URL_LINE}"',
        expect_exit=0,
    ),
    ConfiguredCase(
        id="max_body_line_length exempts a final-paragraph trailer",
        options="max_body_line_length = 20",
        command=f'git commit -m "feat: add thing" -m "short body" -m "{TRAILER}"',
        expect_exit=0,
    ),
    ConfiguredCase(
        id="max_body_line_length never checks the subject",
        options="max_body_line_length = 10",
        command='git commit -m "feat: add a subject past ten"',
        expect_exit=0,
    ),
    # forbidden_patterns
    ConfiguredCase(
        id="forbidden_patterns blocks a commit trailer",
        options="forbidden_patterns = ['(?im)^Claude-Session:']",
        command='git commit -m "feat: add thing" -m "Claude-Session: abc123"',
        expect_exit=2,
        stderr_contains=("forbidden-pattern", "Claude-Session"),
    ),
    ConfiguredCase(
        id="forbidden_patterns blocks a PR body",
        options="forbidden_patterns = ['claude\\.ai/code/session_']",
        command='gh pr create --title "feat: add thing" --body "See claude.ai/code/session_1"',
        expect_exit=2,
        stderr_contains=("forbidden-pattern",),
    ),
    ConfiguredCase(
        id="forbidden_patterns blocks a body-only PR edit",
        options="forbidden_patterns = ['(?im)^Claude-Session:']",
        command='gh pr edit 23 --body "Claude-Session: abc123"',
        expect_exit=2,
        stderr_contains=("forbidden-pattern",),
    ),
    ConfiguredCase(
        id="forbidden_patterns allows a clean message",
        options="forbidden_patterns = ['(?im)^Claude-Session:']",
        command='git commit -m "feat: add thing" -m "Body explains why."',
        expect_exit=0,
    ),
    ConfiguredCase(
        id="an invalid forbidden pattern is dropped and the rest still apply",
        options="forbidden_patterns = ['(unclosed', 'secret']",
        command='git commit -m "feat: add secret handling"',
        expect_exit=2,
        stderr_contains=("ignoring forbidden_patterns entry '(unclosed'", "forbidden-pattern"),
    ),
    # check_pr_titles
    ConfiguredCase(
        id="check_pr_titles false skips the subject rules",
        options="check_pr_titles = false",
        command='gh pr create --title "Add new feature"',
        expect_exit=0,
    ),
    ConfiguredCase(
        id="check_pr_titles false keeps forbidden_patterns on the title",
        options="check_pr_titles = false\nforbidden_patterns = ['WIP']",
        command='gh pr create --title "WIP thing"',
        expect_exit=2,
        stderr_contains=("forbidden-pattern",),
    ),
    # invalid values fall back to the default per key
    ConfiguredCase(
        id="a negative length falls back to the default",
        options="max_subject_length = -1",
        command='git commit -m "feat: ' + ("a" * 95) + '"',
        expect_exit=2,
        stderr_contains=("max_subject_length = -1 must be 0 or more", "subject-too-long"),
    ),
    ConfiguredCase(
        id="an unknown format falls back to conventional",
        options='format = "angular"',
        command='git commit -m "Add new feature"',
        expect_exit=2,
        stderr_contains=("format = 'angular' is not one of", "bad-format"),
    ),
    ConfiguredCase(
        id="an empty types list falls back to the default",
        options="types = []",
        command='git commit -m "chore: tidy things"',
        expect_exit=0,
        stderr_contains=("types is empty",),
    ),
)


@pytest.fixture
def run_configured(
    hooks_dir: Path, tmp_path: Path
) -> Callable[..., subprocess.CompletedProcess[str]]:
    """Return a callable that runs a command under global and optional project configs."""

    def _run(
        command: str, global_options: str, project_options: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        home = tmp_path / "home"
        (home / ".claude").mkdir(parents=True, exist_ok=True)
        (home / ".claude" / "natelandau-toolkit.toml").write_text(
            f"[hooks.commit-message]\n{global_options}\n", encoding="utf-8"
        )
        env = {**clean_environ(), "HOME": str(home)}
        env.pop("CLAUDE_PROJECT_DIR", None)
        if project_options is not None:
            proj = tmp_path / "proj"
            (proj / ".claude").mkdir(parents=True, exist_ok=True)
            (proj / ".claude" / "natelandau-toolkit.toml").write_text(
                f"[hooks.commit-message]\n{project_options}\n", encoding="utf-8"
            )
            env["CLAUDE_PROJECT_DIR"] = str(proj)
        work = tmp_path / "work"
        work.mkdir(exist_ok=True)
        payload = {**_bash(command), "cwd": str(work)}
        return subprocess.run(
            [str(hooks_dir / "pretooluse.py")],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            cwd=str(work),
            env=env,
        )

    return _run


@pytest.mark.parametrize("case", CONFIGURED_CASES, ids=[c.id for c in CONFIGURED_CASES])
def test_enforce_commit_message_configured(
    case: ConfiguredCase, run_configured: Callable[..., subprocess.CompletedProcess[str]]
) -> None:
    """Verify each `[hooks.commit-message]` option changes what the hook blocks."""
    # When invoking the hook under the case's global options
    proc = run_configured(case.command, case.options)

    # Then exit code and stderr content match expectations
    diag = f"\n  stderr={proc.stderr!r}"
    assert proc.returncode == case.expect_exit, f"exit={proc.returncode}{diag}"
    for s in case.stderr_contains:
        assert s in proc.stderr, f"missing {s!r} in stderr{diag}"


def test_project_config_loosens_global_rules(
    run_configured: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    """Verify a project config may widen the global type list."""
    # Given a global config allowing only feat and a project config adding fix
    command = 'git commit -m "fix: handle null input"'

    # When running with and without the project layer
    global_only = run_configured(command, 'types = ["feat"]')
    with_project = run_configured(command, 'types = ["feat"]', 'types = ["feat", "fix"]')

    # Then only the project layer lets the commit through
    assert global_only.returncode == 2, f"stderr={global_only.stderr!r}"
    assert with_project.returncode == 0, f"stderr={with_project.stderr!r}"


def test_forbidden_pattern_in_pr_body_file_blocked(
    run_configured: Callable[..., subprocess.CompletedProcess[str]], tmp_path: Path
) -> None:
    """Verify `--body-file` is read relative to the command's directory and checked."""
    # Given a body file in the working directory carrying a forbidden trailer
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    (work / "pr-body.md").write_text("Adds a thing.\n\nClaude-Session: abc\n", encoding="utf-8")

    # When opening a PR with that body file
    proc = run_configured(
        'gh pr create --title "feat: add thing" --body-file pr-body.md',
        "forbidden_patterns = ['(?im)^Claude-Session:']",
    )

    # Then the hook blocks on the file's content
    assert proc.returncode == 2, f"stderr={proc.stderr!r}"
    assert "forbidden-pattern" in proc.stderr


def test_missing_pr_body_file_fails_open(
    run_configured: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    """Verify an unreadable `--body-file` never blocks the call."""
    # When the body file does not exist
    proc = run_configured(
        'gh pr create --title "feat: add thing" --body-file missing.md',
        "forbidden_patterns = ['.']",
    )

    # Then only the title is checked; "." matches it, proving the title still is
    assert proc.returncode == 2, f"stderr={proc.stderr!r}"
    clean = run_configured(
        "gh pr create --body-file missing.md", "forbidden_patterns = ['(?im)^Claude-Session:']"
    )
    assert clean.returncode == 0, f"stderr={clean.stderr!r}"
