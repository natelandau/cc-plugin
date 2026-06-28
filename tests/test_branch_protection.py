"""Characterization tests for enforce_branch_protection.py.

Pipes representative JSON payloads through the hook (as a subprocess)
against ephemeral git repos and asserts on exit code plus
stdout/stderr substrings.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from types import ModuleType


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
    # A /tmp redirect must not smuggle an unmodeled file-mutating command
    # (sed -i, perl -i, curl -o, wget) past the carve-out: those still write a
    # tracked file, so they stay blocked even with a /tmp redirect attached.
    Case(
        id="sed -i on tracked file with /tmp redirect on master blocked",
        make_payload=lambda r: _bash("sed -i 's/a/b/' app.py 2>/tmp/err", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=("Cannot modify files",),
    ),
    Case(
        id="tmp redirect chained with sed -i on tracked file blocked",
        make_payload=lambda r: _bash(
            "echo ok > /tmp/log && sed -i 's/a/b/' app.py", cwd=r["master"]
        ),
        expect_exit=2,
        stderr_contains=("Cannot modify files",),
    ),
    Case(
        id="wget to tracked file with /tmp redirect on master blocked",
        make_payload=lambda r: _bash(
            "wget http://example.com/x -O app.py 2>/tmp/log", cwd=r["master"]
        ),
        expect_exit=2,
        stderr_contains=("Cannot modify files",),
    ),
    # Protected branch: gitignored write targets allowed on Bash, mirroring the
    # Edit/Write exemption -- a gitignored path is never tracked, so writing it
    # on a protected branch cannot dirty trunk history.
    Case(
        id="touch gitignored dir file on master allowed",
        make_payload=lambda r: _bash("touch ignored_dir/x", cwd=r["master"]),
        expect_exit=0,
    ),
    Case(
        id="mkdir under gitignored dir on master allowed",
        make_payload=lambda r: _bash("mkdir ignored_dir/sub", cwd=r["master"]),
        expect_exit=0,
    ),
    Case(
        id="rm gitignored file on master allowed",
        make_payload=lambda r: _bash("rm notes.ignored", cwd=r["master"]),
        expect_exit=0,
    ),
    Case(
        id="redirect to gitignored file on master allowed",
        make_payload=lambda r: _bash("echo hi > ignored_dir/log", cwd=r["master"]),
        expect_exit=0,
    ),
    Case(
        id="append redirect to gitignored file on master allowed",
        make_payload=lambda r: _bash("echo x >> notes.ignored", cwd=r["master"]),
        expect_exit=0,
    ),
    Case(
        id="chain of gitignored writes on master allowed",
        make_payload=lambda r: _bash(
            "echo hi > ignored_dir/a && rm notes.ignored", cwd=r["master"]
        ),
        expect_exit=0,
    ),
    # Unified carve-out: a command whose writes are all exempt passes even when
    # some go to /tmp and others to a gitignored path.
    Case(
        id="mixed tmp and gitignored writes on master allowed",
        make_payload=lambda r: _bash("touch /tmp/a ignored_dir/b", cwd=r["master"]),
        expect_exit=0,
    ),
    # Safety: a single non-exempt target among exempt ones still blocks -- the
    # carve-out requires EVERY write to be confined.
    Case(
        id="mixed gitignored and tracked write on master blocked",
        make_payload=lambda r: _bash("touch ignored_dir/a tracked.txt", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=("Cannot modify files",),
    ),
    # Safety: sed -i stays declined even on a gitignored file -- its write target
    # can't be confined positionally, same reason the /tmp carve-out excludes it.
    Case(
        id="sed -i on gitignored file on master blocked",
        make_payload=lambda r: _bash("sed -i 's/a/b/' notes.ignored", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=("Cannot modify files",),
    ),
    # Safety: a `..` segment must not let a write masquerade as /tmp-exempt by
    # prefixing /tmp. The target is resolved to its real destination and judged
    # there: a `..` that lands back inside the protected repo is blocked (see the
    # "relative .. traversal into protected repo blocked" case below); one that
    # resolves outside any repo is harmless. Unit coverage in `test_target_protected_branch`.
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
    # Protected branch: merge commits are an ASK (a merge onto trunk is
    # sometimes a deliberate, human-approved integration), routed to the
    # permission prompt via exit 0 + permissionDecision; safe forms pass.
    Case(
        id="git merge --no-ff on master asks",
        make_payload=lambda r: _bash("git merge --no-ff feat", cwd=r["master"]),
        expect_exit=0,
        output_contains=('"permissionDecision": "ask"', "'master'"),
    ),
    Case(
        id="bare git merge on master asks",
        make_payload=lambda r: _bash("git merge feat", cwd=r["master"]),
        expect_exit=0,
        output_contains=('"permissionDecision": "ask"', "'master'"),
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
        id="git pull on master asks",
        make_payload=lambda r: _bash("git pull", cwd=r["master"]),
        expect_exit=0,
        output_contains=('"permissionDecision": "ask"', "'master'"),
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
    # A file-mod Bash command keys off the TARGET's branch, not the shell's:
    # deleting a file outside any repo is harmless even while the shell sits on
    # a protected branch (e.g. curating an external store while the repo is on
    # main). This mirrors the Edit/Write exemption above.
    Case(
        id="rm file outside repo on master allowed",
        make_payload=lambda r: _bash(f"rm {r['outside']}/notes.txt", cwd=r["master"]),
        expect_exit=0,
    ),
    # Safety mirror: a file-mod whose target IS on the protected branch stays
    # blocked, so the per-target check can't be used to delete tracked files.
    Case(
        id="rm tracked file on master blocked",
        make_payload=lambda r: _bash(f"rm {r['master']}/foo.py", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=("Cannot modify files on the 'master' branch",),
    ),
    # === Reverse asymmetry: a file-modifying Bash command is keyed off the
    # branch of the file it TOUCHES, not the shell's cwd. A write into a repo on
    # a protected branch is caught no matter where the shell sits -- mirroring
    # Edit/Write, which already keys off the target file's branch. ===
    Case(
        id="rm into protected repo from feat cwd blocked",
        make_payload=lambda r: _bash(f"rm {r['master']}/foo.py", cwd=r["feat"]),
        expect_exit=2,
        stderr_contains=("Cannot modify files on the 'master' branch",),
    ),
    Case(
        id="redirect into protected repo from feat cwd blocked",
        make_payload=lambda r: _bash(f"echo x > {r['master']}/out.txt", cwd=r["feat"]),
        expect_exit=2,
        stderr_contains=("Cannot modify files on the 'master' branch",),
    ),
    # A gitignored target in a protected repo is still exempt, even reached from
    # a feature-branch cwd: gitignored paths are never tracked history.
    Case(
        id="touch gitignored path in protected repo from feat cwd allowed",
        make_payload=lambda r: _bash(f"touch {r['master']}/ignored_dir/x", cwd=r["feat"]),
        expect_exit=0,
    ),
    # A `..` segment is resolved to its real destination and judged there: a
    # relative traversal that lands back inside the protected repo is blocked.
    Case(
        id="relative .. traversal into protected repo blocked",
        make_payload=lambda r: _bash("echo x > sub/../out.txt", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=("Cannot modify files on the 'master' branch",),
    ),
    # === Target-keyed git commit/merge: the operated-on repo is read from
    # `git -C <path>` and `cd <path> &&`, not assumed to be the shell's cwd. ===
    Case(
        id="git -C protected repo commit from feat cwd blocked",
        make_payload=lambda r: _bash(f"git -C {r['master']} commit -m x", cwd=r["feat"]),
        expect_exit=2,
        stderr_contains=("Cannot commit directly to the 'master' branch",),
    ),
    Case(
        id="cd into protected repo then commit blocked",
        make_payload=lambda r: _bash(f"cd {r['master']} && git commit -m x", cwd=r["feat"]),
        expect_exit=2,
        stderr_contains=("Cannot commit directly to the 'master' branch",),
    ),
    # No false positive in the other direction: committing into a feature-branch
    # repo is fine even when the shell sits on a protected branch.
    Case(
        id="git -C feat repo commit from master cwd allowed",
        make_payload=lambda r: _bash(f"git -C {r['feat']} commit -m x", cwd=r["master"]),
        expect_exit=0,
    ),
    # A merge commit onto a protected branch is an ASK (permission prompt), not a
    # hard DENY: it is sometimes a deliberate, human-approved integration.
    Case(
        id="git -C protected repo merge from feat cwd asks",
        make_payload=lambda r: _bash(f"git -C {r['master']} merge topic", cwd=r["feat"]),
        expect_exit=0,
        output_contains=('"permissionDecision": "ask"', "'master'"),
    ),
    # A safe merge form (--ff-only) onto a protected repo passes silently.
    Case(
        id="git -C protected repo merge --ff-only from feat cwd allowed",
        make_payload=lambda r: _bash(f"git -C {r['master']} merge --ff-only topic", cwd=r["feat"]),
        expect_exit=0,
    ),
    # Precedence: a command that both merges (an ASK) and deletes a tracked file
    # (a DENY) is denied, not merely prompted -- approving the prompt would
    # otherwise let the unconditional file deletion through.
    Case(
        id="merge plus tracked-file delete on master denied not asked",
        make_payload=lambda r: _bash("git merge feat && rm foo.py", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=("Cannot modify files on the 'master' branch",),
    ),
    # Precedence across git clauses: a later direct-commit DENY outranks an
    # earlier merge/pull ASK in the same command, so prepending `git pull` cannot
    # downgrade a hard-blocked commit on master to an approvable prompt.
    Case(
        id="pull then commit on master denied not asked",
        make_payload=lambda r: _bash("git pull && git commit -m x", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=("Cannot commit directly to the 'master' branch",),
    ),
    # cd-tracking applies to file mods too: a relative write after `cd <protected>`
    # is judged against the cd'd-into repo, not the original shell cwd.
    Case(
        id="cd into protected repo then rm relative file blocked",
        make_payload=lambda r: _bash(f"cd {r['master']} && rm foo.py", cwd=r["feat"]),
        expect_exit=2,
        stderr_contains=("Cannot modify files on the 'master' branch",),
    ),
    Case(
        id="cd into protected repo then redirect blocked",
        make_payload=lambda r: _bash(f"cd {r['master']} && echo x > out.txt", cwd=r["feat"]),
        expect_exit=2,
        stderr_contains=("Cannot modify files on the 'master' branch",),
    ),
    # An unconfinable write (sed -i) in an earlier clause must not mask a later
    # confinable write into a protected repo: each clause is judged on its own.
    Case(
        id="unconfinable clause then protected-repo write still blocked",
        make_payload=lambda r: _bash(
            f"sed -i s/a/b/ bar.py && rm {r['master']}/foo.py", cwd=r["feat"]
        ),
        expect_exit=2,
        stderr_contains=("Cannot modify files on the 'master' branch",),
    ),
    # A squash chain written with `git -C <repo>` is recognized, so the follow-up
    # commit is allowed rather than wrongly blocked by the commit guard.
    Case(
        id="git -C squash chain commit allowed",
        make_payload=lambda r: _bash(
            f"git -C {r['master']} merge --squash topic && git -C {r['master']} commit -m x",
            cwd=r["feat"],
        ),
        expect_exit=0,
    ),
    # Quoted command paths are unquoted before the lookup, so quoting cannot hide
    # the real repo/target from the guard.
    Case(
        id="git -C quoted protected repo commit blocked",
        make_payload=lambda r: _bash(f"git -C '{r['master']}' commit -m x", cwd=r["feat"]),
        expect_exit=2,
        stderr_contains=("Cannot commit directly to the 'master' branch",),
    ),
    Case(
        id="rm quoted tracked file in protected repo blocked",
        make_payload=lambda r: _bash(f"rm '{r['master']}/foo.py'", cwd=r["feat"]),
        expect_exit=2,
        stderr_contains=("Cannot modify files on the 'master' branch",),
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


def _load_hook(hooks_dir: Path) -> ModuleType:
    """Import pretooluse/enforce_branch_protection.py in-process for unit tests."""
    sys.path.insert(0, str(hooks_dir))
    try:
        spec = importlib.util.spec_from_file_location(
            "_branch_protection_under_test",
            hooks_dir / "pretooluse" / "enforce_branch_protection.py",
        )
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


def test_target_protected_branch(hooks_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify _target_protected_branch exempts /tmp, off-protected-branch, and gitignored targets.

    Returns the offending branch name when a write is NOT exempt, else None.
    Calls the predicate directly because the empty-cwd and traversal cases can't
    be reached through the dispatcher: an empty event cwd also defeats branch
    detection, so the protected-branch check never runs.
    """
    # Given the module with check-ignore stubbed to the master repo's patterns
    # (*.ignored, ignored_dir/). Stubbing keeps the absolute-path assertions off
    # the real filesystem: pytest's tmp root is under /tmp on Linux, so a real
    # repo path would hit the /tmp carve-out before the gitignore branch ever
    # runs. End-to-end check-ignore behavior is covered by the dispatcher cases.
    m = _load_hook(hooks_dir)

    def fake_is_git_ignored(path: str) -> bool:
        parts = Path(path)
        return parts.suffix == ".ignored" or "ignored_dir" in parts.parts

    # The /repo tree is the protected (master) working tree; anything under
    # /external sits outside any repo, so its branch lookup yields "".
    def fake_branch_at_path(path: str) -> str:
        return "" if "/external" in path else "master"

    monkeypatch.setattr(m, "_is_git_ignored", fake_is_git_ignored)
    monkeypatch.setattr(m, "get_branch_at_path", fake_branch_at_path)
    # A synthetic absolute base outside /tmp; git lookups are stubbed, so it
    # needs no real directory and must not trip the /tmp carve-out.
    base = "/repo"

    # Then /tmp paths are exempt, but a `..` traversal that resolves out of /tmp
    # onto a protected branch is not (it is judged at its real destination)
    assert m._target_protected_branch("/tmp/x", "") is None  # noqa: S108
    assert m._target_protected_branch("/tmp/../tracked.txt", "") == "master"  # noqa: S108

    # Then a target that is not on a protected branch (here, outside any repo)
    # is exempt even though it is not gitignored -- the key is the target's own
    # branch, not the shell's cwd
    assert m._target_protected_branch("/external/store/x.md", "") is None
    assert m._target_protected_branch("x.md", "/external/store") is None

    # Then on a protected branch only gitignored targets are exempt: an absolute
    # gitignored target passes with no cwd, an absolute tracked one does not
    # (cwd is only needed to resolve relative paths)
    assert m._target_protected_branch(f"{base}/ignored_dir/x", "") is None
    assert m._target_protected_branch(f"{base}/foo.py", "") == "master"

    # Then a relative target with a cwd resolves and is judged (gitignored here,
    # so exempt). With no cwd it can't be located, so it can't be attributed to a
    # protected branch and is treated as harmless (the fail-open default).
    assert m._target_protected_branch("ignored_dir/x", base) is None
    assert m._target_protected_branch("ignored_dir/x", "") is None


def test_target_protected_branch_follows_symlink_into_protected_repo(
    repos: Mapping[str, str], hooks_dir: Path, tmp_path: Path
) -> None:
    """Verify a symlink resolving into a protected repo is judged by its real path."""
    # Given a symlink that lives outside any repo but points at a tracked path
    # inside the master repo, which is on a protected branch
    m = _load_hook(hooks_dir)
    link = tmp_path / "sneaky.py"
    link.symlink_to(Path(repos["master"]) / "app.py")
    if m._under_tmp(link.resolve()):
        # When the ephemeral repo itself lives under /tmp (pytest's tmp root on
        # Linux), the temp-root carve-out legitimately exempts the resolved path,
        # so the in-repo block can't be exercised here. On a real checkout the
        # repo is not under /tmp and the symlink resolves to a blocked path.
        pytest.skip("ephemeral repo is under /tmp; temp-root carve-out applies")

    # When checking the symlink target while the repo is on a protected branch
    # Then the branch lookup follows the link to the in-repo path and blocks it,
    # rather than reading the link's own (repo-less) parent directory as exempt
    assert m._target_protected_branch(str(link), "") == "master"
