"""Characterization tests for enforce_branch_protection.py.

Pipes representative JSON payloads through the hook (as a subprocess)
against ephemeral git repos and asserts on exit code plus
stdout/stderr substrings.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping


def _bash(cmd: str, *, cwd: str) -> dict[str, Any]:
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": cmd},
        "cwd": cwd,
    }


def _edit(path: str) -> dict[str, Any]:
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "Edit",
        "tool_input": {"file_path": path},
        "cwd": str(Path(path).parent),
    }


def _write(path: str) -> dict[str, Any]:
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "Write",
        "tool_input": {"file_path": path},
        "cwd": str(Path(path).parent),
    }


def _notebook(path: str) -> dict[str, Any]:
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "NotebookEdit",
        "tool_input": {"notebook_path": path},
        "cwd": str(Path(path).parent),
    }


@dataclass(frozen=True)
class Case:
    """One characterization test case.

    `make_payload` defers payload construction until the `repos` fixture
    is available. Without this indirection the cases would have to either
    bake in fixed paths at import time or use placeholder substitution.
    """

    id: str
    make_payload: Callable[[Mapping[str, str]], dict[str, Any]]
    expect_exit: int
    stderr_contains: tuple[str, ...] = ()
    output_contains: tuple[str, ...] = field(default=())


CASES: tuple[Case, ...] = (
    # Edit/Write/NotebookEdit on protected branch
    Case(
        id="edit on master blocked",
        make_payload=lambda r: _edit(f"{r['master']}/foo.py"),
        expect_exit=2,
        # Protected-branch blocks carry the canonical `BLOCKED [<id>]:` prefix.
        stderr_contains=(
            "BLOCKED [branch-protection]",
            "Cannot modify files on the 'master' branch",
        ),
    ),
    Case(
        id="write on master blocked",
        make_payload=lambda r: _write(f"{r['master']}/foo.py"),
        expect_exit=2,
        stderr_contains=("Cannot modify files on the 'master' branch",),
    ),
    Case(
        id="notebook on master blocked",
        make_payload=lambda r: _notebook(f"{r['master']}/foo.ipynb"),
        expect_exit=2,
        stderr_contains=("Cannot modify files on the 'master' branch",),
    ),
    Case(
        id="edit on feat allowed",
        make_payload=lambda r: _edit(f"{r['feat']}/foo.py"),
        expect_exit=0,
    ),
    # Gitignored paths are never part of trunk history, so editing them on
    # a protected branch is allowed even though the branch is protected.
    Case(
        id="edit gitignored file on master allowed",
        make_payload=lambda r: _edit(f"{r['master']}/notes.ignored"),
        expect_exit=0,
    ),
    Case(
        id="write new file in gitignored dir on master allowed",
        make_payload=lambda r: _write(f"{r['master']}/ignored_dir/new.txt"),
        expect_exit=0,
    ),
    Case(
        id="notebook gitignored on master allowed",
        make_payload=lambda r: _notebook(f"{r['master']}/ignored_dir/nb.ipynb"),
        expect_exit=0,
    ),
    # Destructive git commands (any branch)
    Case(
        id="git push --force blocked on feat",
        make_payload=lambda r: _bash("git push --force origin feat", cwd=r["feat"]),
        expect_exit=2,
        # Destructive blocks carry the canonical `BLOCKED [<id>]:` prefix.
        stderr_contains=("Force push", "BLOCKED [branch-protection]"),
    ),
    Case(
        id="git push -f blocked",
        make_payload=lambda r: _bash("git push -f origin feat", cwd=r["feat"]),
        expect_exit=2,
        stderr_contains=("Force push",),
    ),
    Case(
        id="git push --force-with-lease blocked",
        make_payload=lambda r: _bash("git push --force-with-lease origin feat", cwd=r["feat"]),
        expect_exit=2,
        stderr_contains=("Force push",),
    ),
    Case(
        id="git push +refspec blocked",
        make_payload=lambda r: _bash("git push origin +master", cwd=r["feat"]),
        expect_exit=2,
        stderr_contains=("Force push via refspec",),
    ),
    Case(
        id="git push +HEAD:main blocked",
        make_payload=lambda r: _bash("git push origin +HEAD:main", cwd=r["feat"]),
        expect_exit=2,
        stderr_contains=("Force push via refspec",),
    ),
    Case(
        id="git push without + allowed",
        make_payload=lambda r: _bash("git push origin feat", cwd=r["feat"]),
        expect_exit=0,
    ),
    Case(
        id="git reset --hard blocked",
        make_payload=lambda r: _bash("git reset --hard HEAD~1", cwd=r["feat"]),
        expect_exit=2,
        stderr_contains=("reset --hard",),
    ),
    Case(
        id="git clean -fd blocked",
        make_payload=lambda r: _bash("git clean -fd", cwd=r["feat"]),
        expect_exit=2,
        stderr_contains=("git clean -f",),
    ),
    Case(
        id="git clean -fdn allowed (dry-run exclude)",
        make_payload=lambda r: _bash("git clean -fdn", cwd=r["feat"]),
        expect_exit=0,
    ),
    Case(
        id="git clean --dry-run allowed",
        make_payload=lambda r: _bash("git clean -f --dry-run", cwd=r["feat"]),
        expect_exit=0,
    ),
    Case(
        id="git checkout . blocked",
        make_payload=lambda r: _bash("git checkout .", cwd=r["feat"]),
        expect_exit=2,
        stderr_contains=("git checkout .",),
    ),
    Case(
        id="git checkout -- . blocked",
        make_payload=lambda r: _bash("git checkout -- .", cwd=r["feat"]),
        expect_exit=2,
        stderr_contains=("git checkout .",),
    ),
    Case(
        id="git restore . blocked",
        make_payload=lambda r: _bash("git restore .", cwd=r["feat"]),
        expect_exit=2,
        stderr_contains=("git restore .",),
    ),
    Case(
        id="git rebase --no-verify blocked",
        make_payload=lambda r: _bash("git rebase --no-verify main", cwd=r["feat"]),
        expect_exit=2,
        stderr_contains=("--no-verify",),
    ),
    Case(
        id="git branch -D main blocked",
        make_payload=lambda r: _bash("git branch -D main", cwd=r["feat"]),
        expect_exit=2,
        stderr_contains=("protected branch 'main'",),
    ),
    Case(
        id="git branch -D master blocked",
        make_payload=lambda r: _bash("git branch -D master", cwd=r["feat"]),
        expect_exit=2,
        stderr_contains=("protected branch 'master'",),
    ),
    # Protected branch: file mods blocked
    Case(
        id="rm on master blocked",
        make_payload=lambda r: _bash("rm foo.py", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=("Cannot modify files on the 'master' branch",),
    ),
    Case(
        id="rm on feat allowed",
        make_payload=lambda r: _bash("rm foo.py", cwd=r["feat"]),
        expect_exit=0,
    ),
    Case(
        id="sed -i on master blocked",
        make_payload=lambda r: _bash("sed -i 's/a/b/' foo.py", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=("Cannot modify files",),
    ),
    Case(
        id="perl -i on master blocked",
        make_payload=lambda r: _bash("perl -i -pe 's/a/b/' foo.py", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=("Cannot modify files",),
    ),
    Case(
        id="curl -O on master blocked",
        make_payload=lambda r: _bash("curl -O https://example.com/x", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=("Cannot modify files",),
    ),
    Case(
        id="wget on master blocked",
        make_payload=lambda r: _bash("wget https://example.com/x", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=("Cannot modify files",),
    ),
    Case(
        id="tee on master blocked",
        make_payload=lambda r: _bash("echo hi | tee foo.txt", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=("Cannot modify files",),
    ),
    Case(
        id="output redirect on master blocked",
        make_payload=lambda r: _bash("echo hi > foo.txt", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=("Cannot modify files",),
    ),
    Case(
        id="append redirect on master blocked",
        make_payload=lambda r: _bash("echo hi >> foo.txt", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=("Cannot modify files",),
    ),
    Case(
        id="stderr append 2>> on master blocked",
        make_payload=lambda r: _bash("cmd 2>> log", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=("Cannot modify files",),
    ),
    Case(
        id="stderr redirect 2>&1 allowed on master",
        make_payload=lambda r: _bash("git status 2>&1", cwd=r["master"]),
        expect_exit=0,
    ),
    Case(
        id="find pipe grep with 2>/dev/null allowed on master",
        make_payload=lambda r: _bash(
            f'find {r["master"]} -type f -name "*.py" | xargs grep -l "x" 2>/dev/null',
            cwd=r["master"],
        ),
        expect_exit=0,
    ),
    Case(
        id="redirect to /dev/null allowed on master",
        make_payload=lambda r: _bash("cmd > /dev/null", cwd=r["master"]),
        expect_exit=0,
    ),
    Case(
        id="redirect to /dev/null 2>&1 allowed on master",
        make_payload=lambda r: _bash("cmd > /dev/null 2>&1", cwd=r["master"]),
        expect_exit=0,
    ),
    Case(
        id="stderr redirect to real file 2>err.log on master blocked",
        make_payload=lambda r: _bash("cmd 2>err.log", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=("Cannot modify files",),
    ),
    # Protected branch: /tmp escape
    Case(
        id="rm /tmp/foo on master allowed",
        make_payload=lambda r: _bash("rm /tmp/foo", cwd=r["master"]),
        expect_exit=0,
    ),
    Case(
        id="touch /tmp/x on master allowed",
        make_payload=lambda r: _bash("touch /tmp/x", cwd=r["master"]),
        expect_exit=0,
    ),
    # A redirect whose only write target is under /tmp is a /tmp-only write:
    # the echoed args and the `>` operator are not file paths.
    Case(
        id="redirect to /tmp on master allowed",
        make_payload=lambda r: _bash("echo hi > /tmp/log", cwd=r["master"]),
        expect_exit=0,
    ),
    Case(
        id="append redirect to /tmp on master allowed",
        make_payload=lambda r: _bash("echo config >> /tmp/out.txt", cwd=r["master"]),
        expect_exit=0,
    ),
    Case(
        id="redirect to non-tmp file on master blocked",
        make_payload=lambda r: _bash("echo hi > out.txt", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=("Cannot modify files",),
    ),
    # Protected branch: pure git read commands allowed
    Case(
        id="git status on master allowed",
        make_payload=lambda r: _bash("git status", cwd=r["master"]),
        expect_exit=0,
    ),
    Case(
        id="git log on master allowed",
        make_payload=lambda r: _bash("git log -5", cwd=r["master"]),
        expect_exit=0,
    ),
    Case(
        id="git diff && git status on master allowed",
        make_payload=lambda r: _bash("git diff && git status", cwd=r["master"]),
        expect_exit=0,
    ),
    # Protected branch: git commit blocked, squash exception
    Case(
        id="git commit on master blocked",
        make_payload=lambda r: _bash("git commit -m x", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=("Cannot commit directly to the 'master' branch",),
    ),
    Case(
        id="squash chain commit on master allowed",
        make_payload=lambda r: _bash(
            "git merge --squash foo && git commit -m x",
            cwd=r["master"],
        ),
        expect_exit=0,
    ),
    # Protected branch: merge commits blocked (they write to the branch
    # directly, bypassing the git commit guard), safe forms allowed.
    Case(
        id="git merge --no-ff on master blocked",
        make_payload=lambda r: _bash("git merge --no-ff feat", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=("Cannot merge into the 'master' branch",),
    ),
    Case(
        id="bare git merge on master blocked",
        make_payload=lambda r: _bash("git merge feat", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=("Cannot merge into the 'master' branch",),
    ),
    Case(
        id="git merge --ff-only on master allowed",
        make_payload=lambda r: _bash("git merge --ff-only feat", cwd=r["master"]),
        expect_exit=0,
    ),
    Case(
        id="git merge --ff-only origin trunk on master allowed",
        make_payload=lambda r: _bash("git merge --ff-only origin/master", cwd=r["master"]),
        expect_exit=0,
    ),
    Case(
        id="git merge --squash on master allowed",
        make_payload=lambda r: _bash("git merge --squash feat", cwd=r["master"]),
        expect_exit=0,
    ),
    Case(
        id="git merge --abort on master allowed",
        make_payload=lambda r: _bash("git merge --abort", cwd=r["master"]),
        expect_exit=0,
    ),
    Case(
        id="git pull on master blocked",
        make_payload=lambda r: _bash("git pull", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=("Cannot merge into the 'master' branch",),
    ),
    Case(
        id="git pull --ff-only on master allowed",
        make_payload=lambda r: _bash("git pull --ff-only", cwd=r["master"]),
        expect_exit=0,
    ),
    Case(
        id="git pull --rebase on master allowed",
        make_payload=lambda r: _bash("git pull --rebase", cwd=r["master"]),
        expect_exit=0,
    ),
    # Merges into a feature branch are fine; protection is trunk-only.
    Case(
        id="git merge --no-ff on feat allowed",
        make_payload=lambda r: _bash("git merge --no-ff other", cwd=r["feat"]),
        expect_exit=0,
    ),
    Case(
        id="git pull on feat allowed",
        make_payload=lambda r: _bash("git pull", cwd=r["feat"]),
        expect_exit=0,
    ),
    # git -C advisory (non-blocking): warning may land on stdout or stderr
    Case(
        id="git -C warning emitted on feat",
        make_payload=lambda r: _bash("git -C /tmp status", cwd=r["feat"]),
        expect_exit=0,
        output_contains=("WARNING: Avoid using `git -C",),
    ),
    # Non-Bash, non-file tools pass through
    Case(
        id="Read tool passes",
        make_payload=lambda r: {
            "hook_event_name": "PreToolUse",
            "tool_name": "Read",
            "tool_input": {"file_path": f"{r['master']}/foo.py"},
            "cwd": r["master"],
        },
        expect_exit=0,
    ),
    Case(
        id="Grep tool passes",
        make_payload=lambda r: {
            "hook_event_name": "PreToolUse",
            "tool_name": "Grep",
            "tool_input": {"pattern": "x"},
            "cwd": r["master"],
        },
        expect_exit=0,
    ),
    # Outside git repo: no protection applies
    Case(
        id="edit outside git repo allowed",
        make_payload=lambda r: _edit(f"{r['outside']}/notarepo.txt"),
        expect_exit=0,
    ),
)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_enforce_branch_protection(
    case: Case,
    repos: Mapping[str, str],
    hooks_dir: Path,
) -> None:
    """Verify the hook blocks or allows each action per its rules."""
    # Given a payload built against the ephemeral repos
    hook = hooks_dir / "pretooluse.py"
    payload = case.make_payload(repos)

    # When invoking the hook with the payload on stdin
    proc = subprocess.run(
        [str(hook)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    # Then exit code and stream content match expectations
    diag = f"\n  stderr={proc.stderr!r}\n  stdout={proc.stdout!r}"
    assert proc.returncode == case.expect_exit, f"exit={proc.returncode}{diag}"
    for s in case.stderr_contains:
        assert s in proc.stderr, f"missing {s!r} in stderr{diag}"
    for s in case.output_contains:
        assert s in proc.stdout or s in proc.stderr, f"missing {s!r} in output{diag}"
