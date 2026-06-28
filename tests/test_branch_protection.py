"""Characterization tests for enforce_branch_protection.py.

Pipes representative JSON payloads through the hook (as a subprocess)
against ephemeral git repos and asserts on exit code plus
stdout/stderr substrings. Every block carries the canonical
`BLOCKED [branch-protection]:` stderr prefix.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

import pytest

from tests._env import GIT_REPO_VARS, clean_environ
from tests._helpers import load_hook_module

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from types import ModuleType


class Payload(TypedDict):
    """A PreToolUse hook event payload in the shape the dispatcher delivers."""

    hook_event_name: str
    tool_name: str
    tool_input: dict[str, str]
    cwd: str


def _payload(tool_name: str, tool_input: dict[str, str], cwd: str) -> Payload:
    """Build a PreToolUse payload for any tool -- the one place the envelope is spelled out."""
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": tool_name,
        "tool_input": tool_input,
        "cwd": cwd,
    }


def _bash(cmd: str, *, cwd: str) -> Payload:
    return _payload("Bash", {"command": cmd}, cwd)


def _file_payload(tool_name: str, path: str, *, key: str = "file_path") -> Payload:
    """Build an Edit/Write/NotebookEdit payload, keying cwd off the target's parent dir."""
    return _payload(tool_name, {key: path}, str(Path(path).parent))


def _edit(path: str) -> Payload:
    return _file_payload("Edit", path)


def _write(path: str) -> Payload:
    return _file_payload("Write", path)


def _notebook(path: str) -> Payload:
    return _file_payload("NotebookEdit", path, key="notebook_path")


@dataclass(frozen=True)
class Case:
    """One characterization test case.

    `make_payload` defers payload construction until the `repos` fixture
    is available. Without this indirection the cases would have to either
    bake in fixed paths at import time or use placeholder substitution.
    """

    id: str
    make_payload: Callable[[Mapping[str, str]], Payload]
    expect_exit: int
    stderr_contains: tuple[str, ...] = ()
    output_contains: tuple[str, ...] = ()
    # When set, the command must route to a permission ASK for this branch,
    # asserted by parsing the hook's JSON stdout rather than substring-matching it.
    asks: str | None = None


# Canonical hook messages asserted verbatim across many cases. Naming them once
# keeps a single typo from silently weakening a test.
BLOCK_FILE_MOD = "Cannot modify files on the 'master' branch"
BLOCK_COMMIT = "Cannot commit directly to the 'master' branch"


CASES: tuple[Case, ...] = (
    # Edit/Write/NotebookEdit on protected branch
    Case(
        id="edit on master blocked",
        make_payload=lambda r: _edit(f"{r['master']}/foo.py"),
        expect_exit=2,
        stderr_contains=("BLOCKED [branch-protection]", BLOCK_FILE_MOD),
    ),
    Case(
        id="write on master blocked",
        make_payload=lambda r: _write(f"{r['master']}/foo.py"),
        expect_exit=2,
        stderr_contains=(BLOCK_FILE_MOD,),
    ),
    Case(
        id="notebook on master blocked",
        make_payload=lambda r: _notebook(f"{r['master']}/foo.ipynb"),
        expect_exit=2,
        stderr_contains=(BLOCK_FILE_MOD,),
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
        stderr_contains=(BLOCK_FILE_MOD,),
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
    # Safety: a `..` segment is resolved to its real destination and judged
    # there, so a traversal that lands back inside the protected repo is blocked
    # (see the "relative .. traversal into protected repo blocked" case below)
    # while one that resolves outside any repo is harmless. Unit coverage in
    # `test_target_protected_branch`.
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
        stderr_contains=(BLOCK_COMMIT,),
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
        asks="master",
    ),
    Case(
        id="bare git merge on master asks",
        make_payload=lambda r: _bash("git merge feat", cwd=r["master"]),
        expect_exit=0,
        asks="master",
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
        asks="master",
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
        make_payload=lambda r: _payload(
            "Read", {"file_path": f"{r['master']}/foo.py"}, r["master"]
        ),
        expect_exit=0,
    ),
    Case(
        id="Grep tool passes",
        make_payload=lambda r: _payload("Grep", {"pattern": "x"}, r["master"]),
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
        stderr_contains=(BLOCK_FILE_MOD,),
    ),
    # === Reverse asymmetry: a file-modifying Bash command is keyed off the
    # branch of the file it TOUCHES, not the shell's cwd. A write into a repo on
    # a protected branch is caught no matter where the shell sits -- mirroring
    # Edit/Write, which already keys off the target file's branch. ===
    Case(
        id="rm into protected repo from feat cwd blocked",
        make_payload=lambda r: _bash(f"rm {r['master']}/foo.py", cwd=r["feat"]),
        expect_exit=2,
        stderr_contains=(BLOCK_FILE_MOD,),
    ),
    Case(
        id="redirect into protected repo from feat cwd blocked",
        make_payload=lambda r: _bash(f"echo x > {r['master']}/out.txt", cwd=r["feat"]),
        expect_exit=2,
        stderr_contains=(BLOCK_FILE_MOD,),
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
        stderr_contains=(BLOCK_FILE_MOD,),
    ),
    # === Target-keyed git commit/merge: the operated-on repo is read from
    # `git -C <path>` and `cd <path> &&`, not assumed to be the shell's cwd. ===
    Case(
        id="git -C protected repo commit from feat cwd blocked",
        make_payload=lambda r: _bash(f"git -C {r['master']} commit -m x", cwd=r["feat"]),
        expect_exit=2,
        stderr_contains=(BLOCK_COMMIT,),
    ),
    Case(
        id="cd into protected repo then commit blocked",
        make_payload=lambda r: _bash(f"cd {r['master']} && git commit -m x", cwd=r["feat"]),
        expect_exit=2,
        stderr_contains=(BLOCK_COMMIT,),
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
        asks="master",
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
        stderr_contains=(BLOCK_FILE_MOD,),
    ),
    # Precedence across git clauses: a later direct-commit DENY outranks an
    # earlier merge/pull ASK in the same command, so prepending `git pull` cannot
    # downgrade a hard-blocked commit on master to an approvable prompt.
    Case(
        id="pull then commit on master denied not asked",
        make_payload=lambda r: _bash("git pull && git commit -m x", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=(BLOCK_COMMIT,),
    ),
    # cd-tracking applies to file mods too: a relative write after `cd <protected>`
    # is judged against the cd'd-into repo, not the original shell cwd.
    Case(
        id="cd into protected repo then rm relative file blocked",
        make_payload=lambda r: _bash(f"cd {r['master']} && rm foo.py", cwd=r["feat"]),
        expect_exit=2,
        stderr_contains=(BLOCK_FILE_MOD,),
    ),
    Case(
        id="cd into protected repo then redirect blocked",
        make_payload=lambda r: _bash(f"cd {r['master']} && echo x > out.txt", cwd=r["feat"]),
        expect_exit=2,
        stderr_contains=(BLOCK_FILE_MOD,),
    ),
    # An unconfinable write (sed -i) in an earlier clause must not mask a later
    # confinable write into a protected repo: each clause is judged on its own.
    Case(
        id="unconfinable clause then protected-repo write still blocked",
        make_payload=lambda r: _bash(
            f"sed -i s/a/b/ bar.py && rm {r['master']}/foo.py", cwd=r["feat"]
        ),
        expect_exit=2,
        stderr_contains=(BLOCK_FILE_MOD,),
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
        stderr_contains=(BLOCK_COMMIT,),
    ),
    Case(
        id="rm quoted tracked file in protected repo blocked",
        make_payload=lambda r: _bash(f"rm '{r['master']}/foo.py'", cwd=r["feat"]),
        expect_exit=2,
        stderr_contains=(BLOCK_FILE_MOD,),
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
        # Strip leaked git-location vars (GIT_DIR, ...) so the hook resolves the
        # ephemeral test repos, not the checkout the suite runs from (pre-commit
        # / worktree set these, which would otherwise hijack branch detection).
        env=clean_environ(),
    )

    # Then exit code and stream content match expectations
    diag = f"\n  stderr={proc.stderr!r}\n  stdout={proc.stdout!r}"
    assert proc.returncode == case.expect_exit, f"exit={proc.returncode}{diag}"
    for s in case.stderr_contains:
        assert s in proc.stderr, f"missing {s!r} in stderr{diag}"
    for s in case.output_contains:
        assert s in proc.stdout or s in proc.stderr, f"missing {s!r} in output{diag}"
    if case.asks is not None:
        # An ASK is a structured permission decision on stdout, not a substring:
        # parse it so the assertion survives any reformatting of the JSON.
        assert proc.stdout, f"expected an ask decision on stdout{diag}"
        decision = json.loads(proc.stdout)["hookSpecificOutput"]
        assert decision["permissionDecision"] == "ask", f"not an ask{diag}"
        # Match the quoted branch (`'master'`) so a name that merely contains it
        # (e.g. 'master-backup') can't satisfy the check.
        assert f"'{case.asks}'" in decision["permissionDecisionReason"], f"wrong branch{diag}"


def _load_hook(hooks_dir: Path) -> ModuleType:
    """Import pretooluse/enforce_branch_protection.py in-process for unit tests."""
    return load_hook_module(
        hooks_dir, "pretooluse/enforce_branch_protection.py", "_branch_protection_under_test"
    )


def test_target_protected_branch(hooks_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify _target_protected_branch flags only tracked targets in a protected repo."""
    # The predicate returns the offending branch name when a write is NOT exempt,
    # else None. We call it directly because the empty-cwd case can't be reached
    # through the dispatcher: an empty event cwd also defeats branch detection, so
    # the protected-branch check never runs.
    # Given the module with branch + check-ignore stubbed. Only the synthetic
    # /repo tree is a protected working tree; /tmp, /external, and anything else
    # sit outside any repo, so their branch lookup yields "" (the realistic
    # result, since /tmp is not a git repo). Stubbing keeps the assertions off the
    # real filesystem; end-to-end behavior is covered by the dispatcher cases.
    m = _load_hook(hooks_dir)

    def fake_is_git_ignored(path: str) -> bool:
        parts = Path(path)
        return parts.suffix == ".ignored" or "ignored_dir" in parts.parts

    def fake_branch_at_path(path: str) -> str:
        return "master" if path.startswith("/repo") else ""

    monkeypatch.setattr(m, "_is_git_ignored", fake_is_git_ignored)
    monkeypatch.setattr(m, "get_branch_at_path", fake_branch_at_path)
    base = "/repo"

    # Then a target outside any repo is exempt -- a /tmp scratch path or a `..`
    # that resolves out of every repo both yield "" from the branch lookup
    assert m._target_protected_branch("/tmp/x", "") is None  # noqa: S108
    assert m._target_protected_branch("/tmp/../tracked.txt", "") is None  # noqa: S108
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
    repos: Mapping[str, str], hooks_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify a symlink resolving into a protected repo is judged by its real path."""
    # Given a symlink that lives outside any repo but points at a tracked path
    # inside the master repo, which is on a protected branch. The predicate runs
    # git in-process, so any leaked git-location vars (pre-commit / worktree) must
    # be cleared or they would hijack branch detection to the outer checkout.
    for var in GIT_REPO_VARS:
        monkeypatch.delenv(var, raising=False)
    m = _load_hook(hooks_dir)
    link = tmp_path / "sneaky.py"
    link.symlink_to(Path(repos["master"]) / "app.py")

    # When checking the symlink target while the repo is on a protected branch
    # Then the branch lookup follows the link to the in-repo path and blocks it,
    # rather than reading the link's own (repo-less) parent directory as exempt
    assert m._target_protected_branch(str(link), "") == "master"


def test_get_branch_at_path_ignores_ambient_git_dir(
    repos: Mapping[str, str], hooks_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify branch detection honors the -C path over an inherited GIT_DIR."""
    # Given an ambient GIT_DIR naming a different repo (master). Git exports it
    # when running a hook or from a linked worktree; an absolute GIT_DIR overrides
    # `git -C`, so without sanitizing it every lookup would report master's branch.
    m = _load_hook(hooks_dir)
    monkeypatch.setenv("GIT_DIR", str(Path(repos["master"]) / ".git"))
    # When resolving the feat repo's branch
    branch = m.get_branch_at_path(repos["feat"])
    # Then the -C path wins: feat's own branch, not the leaked master
    assert branch == "feat"
