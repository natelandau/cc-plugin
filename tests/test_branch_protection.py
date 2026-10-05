"""Characterization tests for enforce_branch_protection.py.

Pipes representative JSON payloads through the hook (as a subprocess)
against ephemeral git repos and asserts on exit code plus
stdout/stderr substrings. Every block carries the canonical
`BLOCKED [branch-protection]:` stderr prefix.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

import pytest

from tests._env import clean_environ, exempt_env
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
    # A backslash-continued newline is whitespace inside one command, not a
    # statement separator, so a flag on the next line still belongs to the git
    # command on the first.
    Case(
        id="git push --force across a line continuation blocked",
        make_payload=lambda r: _bash("git push \\\n--force origin feat", cwd=r["feat"]),
        expect_exit=2,
        stderr_contains=("Force push",),
    ),
    Case(
        id="git reset --hard across a line continuation blocked",
        make_payload=lambda r: _bash("git reset \\\n--hard HEAD~1", cwd=r["feat"]),
        expect_exit=2,
        stderr_contains=("reset --hard",),
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
        id="git restore --staged . allowed (unstage only, worktree untouched)",
        make_payload=lambda r: _bash("git restore --staged .", cwd=r["feat"]),
        expect_exit=0,
    ),
    Case(
        id="git restore -S . allowed (short staged flag)",
        make_payload=lambda r: _bash("git restore -S .", cwd=r["feat"]),
        expect_exit=0,
    ),
    Case(
        id="git restore --source=HEAD --staged . allowed (index only)",
        make_payload=lambda r: _bash("git restore --source=HEAD --staged .", cwd=r["feat"]),
        expect_exit=0,
    ),
    Case(
        id="git restore --staged --worktree . blocked (worktree restored)",
        make_payload=lambda r: _bash("git restore --staged --worktree .", cwd=r["feat"]),
        expect_exit=2,
        stderr_contains=("git restore .",),
    ),
    Case(
        id="git restore -SW . blocked (combined short worktree flag)",
        make_payload=lambda r: _bash("git restore -SW .", cwd=r["feat"]),
        expect_exit=2,
        stderr_contains=("git restore .",),
    ),
    Case(
        id="git restore -W . blocked (short worktree flag)",
        make_payload=lambda r: _bash("git restore -W .", cwd=r["feat"]),
        expect_exit=2,
        stderr_contains=("git restore .",),
    ),
    Case(
        id="git restore --source=HEAD . blocked (worktree from source, no staged)",
        make_payload=lambda r: _bash("git restore --source=HEAD .", cwd=r["feat"]),
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
    # Inline interpreter programs are not judged by their launch line: the
    # program text decides what they write, and a launch-shape rule cannot see
    # it. A redirect on the same command is still read like any other.
    Case(
        id="python heredoc script on master allowed",
        make_payload=lambda r: _bash("python3 - <<'EOF'\nprint(1)\nEOF", cwd=r["master"]),
        expect_exit=0,
    ),
    Case(
        id="python -c on master allowed",
        make_payload=lambda r: _bash('python3 -c "print(1)"', cwd=r["master"]),
        expect_exit=0,
    ),
    Case(
        id="python fed by a pipe on master allowed",
        make_payload=lambda r: _bash(
            "cat data.json | python3 -c 'import json,sys'", cwd=r["master"]
        ),
        expect_exit=0,
    ),
    Case(
        id="uv run python -c on master allowed",
        make_payload=lambda r: _bash("uv run python -c 'print(1)'", cwd=r["master"]),
        expect_exit=0,
    ),
    Case(
        id="node -e on master allowed",
        make_payload=lambda r: _bash("node -e 'console.log(1)'", cwd=r["master"]),
        expect_exit=0,
    ),
    Case(
        id="python -c redirected into the repo on master blocked",
        make_payload=lambda r: _bash("python3 -c 'print(1)' > foo.py", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=(BLOCK_FILE_MOD,),
    ),
    # Running a script file, a module, or a tool is an ordinary dev action.
    Case(
        id="python script file on master allowed",
        make_payload=lambda r: _bash("python3 tool.py", cwd=r["master"]),
        expect_exit=0,
    ),
    Case(
        id="python -m module on master allowed",
        make_payload=lambda r: _bash("python3 -m pytest -p no:cacheprovider", cwd=r["master"]),
        expect_exit=0,
    ),
    Case(
        id="python -W flag with script on master allowed",
        make_payload=lambda r: _bash("python3 -Werror tool.py", cwd=r["master"]),
        expect_exit=0,
    ),
    Case(
        id="python --version on master allowed",
        make_payload=lambda r: _bash("python3 --version", cwd=r["master"]),
        expect_exit=0,
    ),
    Case(
        id="node --version on master allowed",
        make_payload=lambda r: _bash("node --version", cwd=r["master"]),
        expect_exit=0,
    ),
    Case(
        id="uv run pytest on master allowed",
        make_payload=lambda r: _bash("uv run pytest -p no:cacheprovider", cwd=r["master"]),
        expect_exit=0,
    ),
    Case(
        id="uv run script file on master allowed",
        make_payload=lambda r: _bash("uv run --script tool.py", cwd=r["master"]),
        expect_exit=0,
    ),
    Case(
        id="uv run tool fed a heredoc on master allowed",
        make_payload=lambda r: _bash(
            "uv run sessionmemory new spec --title x --cwd . --body-file - <<'EOF'\n# hi\nEOF",
            cwd=r["master"],
        ),
        expect_exit=0,
    ),
    Case(
        id="uv run pytest fed a heredoc on master allowed",
        make_payload=lambda r: _bash("uv run pytest -q <<'EOF'\nx\nEOF", cwd=r["master"]),
        expect_exit=0,
    ),
    Case(
        id="python script file fed a heredoc on master allowed",
        make_payload=lambda r: _bash("python3 tool.py <<'EOF'\nx\nEOF", cwd=r["master"]),
        expect_exit=0,
    ),
    Case(
        id="python module fed a heredoc on master allowed",
        make_payload=lambda r: _bash("python3 -m json.tool <<'EOF'\n{}\nEOF", cwd=r["master"]),
        expect_exit=0,
    ),
    Case(
        id="node script file on master allowed",
        make_payload=lambda r: _bash("node build.js", cwd=r["master"]),
        expect_exit=0,
    ),
    Case(
        id="interpreter name as an argument on master allowed",
        make_payload=lambda r: _bash("which python3 && grep -rn python3 -e x", cwd=r["master"]),
        expect_exit=0,
    ),
    Case(
        id="interpreter name inside quotes on master allowed",
        make_payload=lambda r: _bash("echo 'python3 -c x'", cwd=r["master"]),
        expect_exit=0,
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
    # === Quote-aware parsing: a `>`/`&&`/`;`/`|` inside quotes is DATA, not a
    # redirect or clause operator, so a read-only command carrying one in a
    # quoted program (awk/grep/jq/echo) passes on a protected branch. Without
    # quote-awareness the `>` in `c>=2` reads as an output redirect and blocks. ===
    Case(
        id="awk with quoted >= on master allowed",
        make_payload=lambda r: _bash("awk '/^---$/{c++} c>=2{exit}' foo.md", cwd=r["master"]),
        expect_exit=0,
    ),
    Case(
        id="awk with quoted > comparison on master allowed",
        make_payload=lambda r: _bash("awk '$3 > 100 {print $1}' data.txt", cwd=r["master"]),
        expect_exit=0,
    ),
    Case(
        id="grep with quoted > on master allowed",
        make_payload=lambda r: _bash("grep 'a > b' foo.txt", cwd=r["master"]),
        expect_exit=0,
    ),
    Case(
        id="jq with quoted > on master allowed",
        make_payload=lambda r: _bash("jq '.a > .b' data.json", cwd=r["master"]),
        expect_exit=0,
    ),
    Case(
        id="echo quoted redirect literal on master allowed",
        make_payload=lambda r: _bash("echo 'write with > inside'", cwd=r["master"]),
        expect_exit=0,
    ),
    Case(
        id="printf with quoted > on master allowed",
        make_payload=lambda r: _bash('printf "%s\\n" "1 > 2"', cwd=r["master"]),
        expect_exit=0,
    ),
    Case(
        id="sed read-only print on master allowed",
        make_payload=lambda r: _bash("sed -n '/x/p' foo.txt", cwd=r["master"]),
        expect_exit=0,
    ),
    # A quoted operator must not HIDE a real write spliced onto the command: the
    # genuine redirect/operator still parses and still blocks.
    Case(
        id="awk quoted program with real redirect on master blocked",
        make_payload=lambda r: _bash("awk '{print $1}' data.txt > out.txt", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=("Cannot modify files",),
    ),
    Case(
        id="grep quoted > with real redirect on master blocked",
        make_payload=lambda r: _bash("grep 'a>b' foo.txt > results.txt", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=("Cannot modify files",),
    ),
    # A quoted sequence operator must not mask a real second clause: the real
    # unquoted `;`/`&&` still splits and the trailing file mod is still caught.
    Case(
        id="quoted semicolon then real rm on master blocked",
        make_payload=lambda r: _bash("echo 'a ; b' ; rm foo.py", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=(BLOCK_FILE_MOD,),
    ),
    Case(
        id="quoted && then real rm on master blocked",
        make_payload=lambda r: _bash('echo "x && y" && rm foo.py', cwd=r["master"]),
        expect_exit=2,
        stderr_contains=(BLOCK_FILE_MOD,),
    ),
    # A quoted `;` keeps the whole thing one read-only clause: the literal `rm`
    # inside the quotes is text and must NOT be treated as a delete.
    Case(
        id="echo with quoted rm command on master allowed",
        make_payload=lambda r: _bash("echo 'rm foo.py'", cwd=r["master"]),
        expect_exit=0,
    ),
    # === Arithmetic / test comparisons: a bare `>` in `(( ))`, `$(( ))`, or
    # `[[ ]]` compares values, it does not redirect, so these read-only commands
    # pass on a protected branch. ===
    Case(
        id="arithmetic command comparison on master allowed",
        make_payload=lambda r: _bash("if (( 5 > 3 )); then echo big; fi", cwd=r["master"]),
        expect_exit=0,
    ),
    Case(
        id="arithmetic expansion comparison on master allowed",
        make_payload=lambda r: _bash("echo $((3 > 2))", cwd=r["master"]),
        expect_exit=0,
    ),
    Case(
        id="test expression comparison on master allowed",
        make_payload=lambda r: _bash("[[ 5 > 3 ]] && echo big", cwd=r["master"]),
        expect_exit=0,
    ),
    # Safety: the arithmetic/test carve-out must NOT extend into a command
    # substitution, whose body runs -- a real redirect inside one still blocks.
    Case(
        id="redirect inside command substitution on master blocked",
        make_payload=lambda r: _bash("result=$(cat a > out.txt)", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=("Cannot modify files",),
    ),
    Case(
        id="arith ok but command-sub redirect on master blocked",
        make_payload=lambda r: _bash("(( a > b )) && echo $(cat a > out.txt)", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=("Cannot modify files",),
    ),
    # === High-confidence filesystem writes that the redirect/positional model
    # cannot confine: blocked on a protected branch, allowed on a feature branch
    # (branch-keyed, like every other file mod). ===
    Case(
        id="truncate on master blocked",
        make_payload=lambda r: _bash("truncate -s 0 foo.py", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=("Cannot modify files",),
    ),
    Case(
        id="truncate on feat allowed",
        make_payload=lambda r: _bash("truncate -s 0 foo.py", cwd=r["feat"]),
        expect_exit=0,
    ),
    Case(
        id="dd of= file on master blocked",
        make_payload=lambda r: _bash("dd if=/dev/zero of=foo.py", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=("Cannot modify files",),
    ),
    Case(
        id="dd of=/dev/null on master allowed",
        make_payload=lambda r: _bash("dd if=foo.py of=/dev/null", cwd=r["master"]),
        expect_exit=0,
    ),
    Case(
        id="find -delete on master blocked",
        make_payload=lambda r: _bash("find . -name '*.py' -delete", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=("Cannot modify files",),
    ),
    Case(
        id="xargs rm on master blocked",
        make_payload=lambda r: _bash("find . -name '*.py' | xargs rm", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=("Cannot modify files",),
    ),
    Case(
        id="xargs -0 rm on master blocked",
        make_payload=lambda r: _bash("find . -print0 | xargs -0 rm", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=("Cannot modify files",),
    ),
    # No false positive: `xargs grep rm` searches for the text "rm", it does not
    # run rm, so it passes.
    Case(
        id="xargs grep for rm text on master allowed",
        make_payload=lambda r: _bash("find . | xargs grep rm", cwd=r["master"]),
        expect_exit=0,
    ),
    # === git working-tree writes (apply/am/stash pop) dirty tracked files on a
    # protected branch, so they get the file-mod deny; read-only inspections and
    # feature branches pass. ===
    Case(
        id="git apply on master blocked",
        make_payload=lambda r: _bash("git apply patch.diff", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=("Cannot modify files",),
    ),
    Case(
        id="git apply on feat allowed",
        make_payload=lambda r: _bash("git apply patch.diff", cwd=r["feat"]),
        expect_exit=0,
    ),
    Case(
        id="git apply --check on master allowed",
        make_payload=lambda r: _bash("git apply --check patch.diff", cwd=r["master"]),
        expect_exit=0,
    ),
    Case(
        id="git am on master blocked",
        make_payload=lambda r: _bash("git am patch.mbox", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=("Cannot modify files",),
    ),
    Case(
        id="git stash pop on master blocked",
        make_payload=lambda r: _bash("git stash pop", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=("Cannot modify files",),
    ),
    Case(
        id="git stash pop on feat allowed",
        make_payload=lambda r: _bash("git stash pop", cwd=r["feat"]),
        expect_exit=0,
    ),
    Case(
        id="git stash list on master allowed",
        make_payload=lambda r: _bash("git stash list", cwd=r["master"]),
        expect_exit=0,
    ),
    # git am / apply read-only and recovery forms touch nothing, so they pass on a
    # protected branch; the inspect/control flags are matched at a flag position
    # so a patch FILENAME containing the text does not flip a real apply.
    Case(
        id="git am --abort on master allowed",
        make_payload=lambda r: _bash("git am --abort", cwd=r["master"]),
        expect_exit=0,
    ),
    Case(
        id="git am --show-current-patch on master allowed",
        make_payload=lambda r: _bash("git am --show-current-patch", cwd=r["master"]),
        expect_exit=0,
    ),
    Case(
        id="git apply --numstat on master allowed",
        make_payload=lambda r: _bash("git apply --numstat patch.diff", cwd=r["master"]),
        expect_exit=0,
    ),
    Case(
        id="git am patch filename containing --check on master blocked",
        make_payload=lambda r: _bash("git am 0001--check.patch", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=("Cannot modify files",),
    ),
    # === Subshell / brace group: a file mod inside `( ... )` / `{ ...; }` is still
    # the command it runs, so the leading group opener does not hide it; the
    # exempt-path carve-out still applies to the confinable target. ===
    Case(
        id="rm in subshell on master blocked",
        make_payload=lambda r: _bash("( rm foo.py )", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=(BLOCK_FILE_MOD,),
    ),
    Case(
        id="rm in subshell no spaces on master blocked",
        make_payload=lambda r: _bash("(rm foo.py)", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=(BLOCK_FILE_MOD,),
    ),
    Case(
        id="rm in brace group on master blocked",
        make_payload=lambda r: _bash("{ rm foo.py; }", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=(BLOCK_FILE_MOD,),
    ),
    Case(
        id="rm under tmp in subshell on master allowed",
        make_payload=lambda r: _bash("( rm /tmp/scratch )", cwd=r["master"]),
        expect_exit=0,
    ),
    # A literal `[[` argument is not a test keyword, so a real redirect after it
    # is still seen and blocked (regression guard for the arithmetic/test mask).
    Case(
        id="echo literal bracket with redirect on master blocked",
        make_payload=lambda r: _bash("echo [[ > out.txt", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=("Cannot modify files",),
    ),
    # === Command-head normalization: a file-mod whose executable hides behind a
    # launcher (`sudo`/`env`/`command`/`nice`/`time`), an env-assignment, or a
    # path is resolved to its basename, so these no longer slip the head-anchored
    # rules on a protected branch. ===
    Case(
        id="sudo rm on master blocked",
        make_payload=lambda r: _bash("sudo rm -rf foo.py", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=(BLOCK_FILE_MOD,),
    ),
    Case(
        id="sudo rm on feat allowed",
        make_payload=lambda r: _bash("sudo rm -rf foo.py", cwd=r["feat"]),
        expect_exit=0,
    ),
    Case(
        id="absolute-path rm on master blocked",
        make_payload=lambda r: _bash("/bin/rm foo.py", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=(BLOCK_FILE_MOD,),
    ),
    Case(
        id="command-builtin rm on master blocked",
        make_payload=lambda r: _bash("command rm foo.py", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=(BLOCK_FILE_MOD,),
    ),
    Case(
        id="env-assignment prefix rm on master blocked",
        make_payload=lambda r: _bash("env FOO=bar rm foo.py", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=(BLOCK_FILE_MOD,),
    ),
    # The exempt-path carve-out survives a wrapper: a wrapped delete whose only
    # target is under /tmp is still a /tmp-only write.
    Case(
        id="sudo rm under tmp on master allowed",
        make_payload=lambda r: _bash("sudo rm /tmp/scratch", cwd=r["master"]),
        expect_exit=0,
    ),
    # A read-only lookup (`command -v rm`) has no target after the executable, so
    # it is not a write and passes.
    Case(
        id="command -v rm lookup on master allowed",
        make_payload=lambda r: _bash("command -v rm", cwd=r["master"]),
        expect_exit=0,
    ),
    # An anchored non-FILE_MOD writer (wget/truncate) behind a wrapper is caught
    # via the de-wrapped command, not just the bare rm-family set.
    Case(
        id="sudo wget on master blocked",
        make_payload=lambda r: _bash("sudo wget http://example.com/x", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=("Cannot modify files",),
    ),
    Case(
        id="sudo truncate on master blocked",
        make_payload=lambda r: _bash("sudo truncate -s 0 foo.py", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=("Cannot modify files",),
    ),
    # Regression guard: a `NAME=$(...)` command-substitution assignment must not
    # be mistaken for a plain env-assignment and dropped -- the writer inside it
    # (here `sed -i`) is still seen via the full-remainder match.
    Case(
        id="command-sub assignment with sed -i on master blocked",
        make_payload=lambda r: _bash("x=$(sed -i 's/a/b/' foo.py)", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=("Cannot modify files",),
    ),
    # A command substitution runs its body, so a write hidden in one is judged
    # like any other command.
    Case(
        id="command-sub hidden rm on master blocked",
        make_payload=lambda r: _bash("echo $(rm foo.py)", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=(BLOCK_FILE_MOD,),
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
    # === Pipeline stages: a flag rule reads only the stage of the command it
    # names, so a flag on a later stage (`grep -i`, `grep -o`, `grep -f`) is not
    # credited to an earlier `sed`/`perl`/`curl`/`git push`. ===
    Case(
        id="sed -n piped to grep -i on master allowed",
        make_payload=lambda r: _bash(
            "sed -n 1,80p web/app.ts 2>/dev/null | grep -n -i -E 'video|screenshot'",
            cwd=r["master"],
        ),
        expect_exit=0,
    ),
    Case(
        id="cd then read-only grep and sed pipelines on master allowed",
        make_payload=lambda r: _bash(
            f"cd {r['master']}; grep -rIl -i -E 'screenshot|recordvideo' "
            "--exclude-dir=node_modules . 2>/dev/null | head -20; "
            "sed -n 1,80p web/app.ts 2>/dev/null | grep -n -i -E 'video|screenshot'",
            cwd=r["master"],
        ),
        expect_exit=0,
    ),
    Case(
        id="detached worktree add then sed piped to grep -i on master allowed",
        make_payload=lambda r: _bash(
            f"git -C {r['master']} worktree add --detach .worktrees/eval abc1234 2>&1 "
            f"| tail -2; sed -n 1,80p {r['master']}/CLAUDE.md | grep -n -i -E 'worktree'",
            cwd=r["master"],
        ),
        expect_exit=0,
    ),
    Case(
        id="perl read piped to grep -i on master allowed",
        make_payload=lambda r: _bash("perl -ne 'print' foo.txt | grep -i x", cwd=r["master"]),
        expect_exit=0,
    ),
    Case(
        id="curl to stdout piped to grep -o on master allowed",
        make_payload=lambda r: _bash(
            "curl -s https://example.com | grep -o 'href'", cwd=r["master"]
        ),
        expect_exit=0,
    ),
    Case(
        id="git push piped to grep -f not read as a force push",
        make_payload=lambda r: _bash("git push origin feat 2>&1 | grep -f pats", cwd=r["feat"]),
        expect_exit=0,
    ),
    Case(
        id="sed -i in a later pipeline stage on master blocked",
        make_payload=lambda r: _bash("cat foo.txt | sed -i 's/a/b/' foo.py", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=(BLOCK_FILE_MOD,),
    ),
    Case(
        id="sed -i with a quoted pipe delimiter on master blocked",
        make_payload=lambda r: _bash("sed 's|a|b|' -i foo.py", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=(BLOCK_FILE_MOD,),
    ),
    Case(
        id="rm as a later pipeline stage on master blocked",
        make_payload=lambda r: _bash("echo y | rm -i foo.py", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=(BLOCK_FILE_MOD,),
    ),
    Case(
        id="curl -o after a 2>&1 dup on master blocked",
        make_payload=lambda r: _bash(
            "curl -s https://example.com 2>&1 -o out.html", cwd=r["master"]
        ),
        expect_exit=2,
        stderr_contains=(BLOCK_FILE_MOD,),
    ),
    Case(
        id="git push --force piped to tail still blocked",
        make_payload=lambda r: _bash("git push --force origin feat 2>&1 | tail -2", cwd=r["feat"]),
        expect_exit=2,
        stderr_contains=("Force push",),
    ),
    # === `git worktree add` creates a separate checkout and leaves the main
    # checkout's files untouched, with or without a new branch. ===
    Case(
        id="detached worktree add on master allowed",
        make_payload=lambda r: _bash(
            "git worktree add --detach .worktrees/eval abc1234", cwd=r["master"]
        ),
        expect_exit=0,
    ),
    Case(
        id="worktree add at a commit-ish on master allowed",
        make_payload=lambda r: _bash("git worktree add .worktrees/eval abc1234", cwd=r["master"]),
        expect_exit=0,
    ),
    # === chmod's mode and chown's owner operand are not paths: only the files
    # after them are write targets, each judged by its own repo's branch. ===
    Case(
        id="chmod +x on a feat-repo file from a master cwd allowed",
        make_payload=lambda r: _bash(f"chmod +x {r['feat']}/scripts/run.sh", cwd=r["master"]),
        expect_exit=0,
    ),
    Case(
        id="script run then chmod +x into feat repo from a master cwd allowed",
        make_payload=lambda r: _bash(
            f'{r["outside"]}/preflight.py ios web; echo "exit $?"; '
            f"chmod +x {r['feat']}/scripts/run.sh",
            cwd=r["master"],
        ),
        expect_exit=0,
    ),
    Case(
        id="chmod octal mode on a feat-repo file from a master cwd allowed",
        make_payload=lambda r: _bash(f"chmod -R 755 {r['feat']}/scripts", cwd=r["master"]),
        expect_exit=0,
    ),
    Case(
        id="chmod symbolic mode list on a feat-repo file from a master cwd allowed",
        make_payload=lambda r: _bash(f"chmod u+x,go-w {r['feat']}/run.sh", cwd=r["master"]),
        expect_exit=0,
    ),
    Case(
        id="chown owner:group on a feat-repo file from a master cwd allowed",
        make_payload=lambda r: _bash(f"chown -R nate:staff {r['feat']}/run.sh", cwd=r["master"]),
        expect_exit=0,
    ),
    Case(
        id="chmod +x on an absolute master-repo file from a feat cwd blocked",
        make_payload=lambda r: _bash(f"chmod +x {r['master']}/foo.py", cwd=r["feat"]),
        expect_exit=2,
        stderr_contains=(BLOCK_FILE_MOD,),
    ),
    Case(
        id="chmod +x on a relative file on master blocked",
        make_payload=lambda r: _bash("chmod +x foo.py", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=(BLOCK_FILE_MOD,),
    ),
    Case(
        id="chmod --reference keeps its first operand as a target",
        make_payload=lambda r: _bash(
            f"chmod --reference=ref.txt {r['master']}/foo.py", cwd=r["feat"]
        ),
        expect_exit=2,
        stderr_contains=(BLOCK_FILE_MOD,),
    ),
    Case(
        id="chown --reference keeps its first operand as a target",
        make_payload=lambda r: _bash(
            f"chown --reference=ref.txt {r['master']}/foo.py", cwd=r["feat"]
        ),
        expect_exit=2,
        stderr_contains=(BLOCK_FILE_MOD,),
    ),
    Case(
        id="chown owner on an absolute master-repo file from a feat cwd blocked",
        make_payload=lambda r: _bash(f"chown nate {r['master']}/foo.py", cwd=r["feat"]),
        expect_exit=2,
        stderr_contains=(BLOCK_FILE_MOD,),
    ),
    # === In-place flags are read in every spelling: bundled short flags
    # (`-Ei`, `-ni`, `-pi`) and sed's long `--in-place`. ===
    *(
        Case(
            id=f"{cmd.split()[0]} in-place form {cmd.split()[1]} on master blocked",
            make_payload=lambda r, cmd=cmd: _bash(cmd, cwd=r["master"]),
            expect_exit=2,
            stderr_contains=(BLOCK_FILE_MOD,),
        )
        for cmd in (
            "sed -Ei 's/a/b/' foo.py",
            "sed -ni 's/a/b/p' foo.py",
            "sed --in-place 's/a/b/' foo.py",
            "sed --in-place=.bak 's/a/b/' foo.py",
            "perl -pi -e 's/a/b/' foo.py",
            "perl -0777pi -e 's/a/b/' foo.py",
        )
    ),
    # A perl `-M` module name that contains an `i` is not an in-place flag.
    Case(
        id="perl -MList::Util read on master allowed",
        make_payload=lambda r: _bash("perl -MList::Util=sum -ne 'print' foo.txt", cwd=r["master"]),
        expect_exit=0,
    ),
    # === Deleting a whole repo on a protected branch is a write to every
    # tracked file in it, and it stays blocked even when the repo lives under a
    # temp dir: under the minimal profile, or with confirm-recursive-rm
    # disabled, this is the only hook that guards a repo delete. ===
    Case(
        id="rm -rf of a whole repo root on master blocked",
        make_payload=lambda r: _bash(f"rm -rf {r['master']}", cwd=r["feat"]),
        expect_exit=2,
        stderr_contains=(BLOCK_FILE_MOD,),
    ),
    Case(
        id="list then rm -rf of a whole repo root on master blocked",
        make_payload=lambda r: _bash(
            f"find {r['master']} -not -path '*/.git/*' | head; "
            f"rm -rf {r['master']} && echo removed",
            cwd=r["outside"],
        ),
        expect_exit=2,
        stderr_contains=(BLOCK_FILE_MOD,),
    ),
    # === A pipe inside a command substitution or process substitution does
    # not end the outer stage, so flags after it stay with the outer command. ===
    *(
        Case(
            id=f"destructive flag after a piped substitution blocked: {cmd}",
            make_payload=lambda r, cmd=cmd: _bash(cmd, cwd=r["feat"]),
            expect_exit=2,
            stderr_contains=("BLOCKED [branch-protection]",),
        )
        for cmd in (
            "git push origin $(git branch --show-current | head -1) --force",
            "git push origin $(git branch --show-current | head -1) -f",
            "git push origin `git branch --show-current | head -1` --force",
            "git reset $(git merge-base HEAD main | cat) --hard",
            "git clean $(echo -d | cat) -f",
        )
    ),
    *(
        Case(
            id=f"in-place flag after a piped substitution on master blocked: {cmd}",
            make_payload=lambda r, cmd=cmd: _bash(cmd, cwd=r["master"]),
            expect_exit=2,
            stderr_contains=(BLOCK_FILE_MOD,),
        )
        for cmd in (
            "sed -e $(echo s/a/b/ | cat) -i foo.py",
            "sed -e `echo s/a/b/ | cat` -i foo.py",
            "sed -e s/a/b/ <(echo | cat) -i foo.py",
            "curl -s $(echo http://x | cat) -o foo.py",
        )
    ),
    Case(
        id="sed -i inside a command substitution on master still blocked",
        make_payload=lambda r: _bash("x=$(echo a | sed -i 's/a/b/' foo.py)", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=(BLOCK_FILE_MOD,),
    ),
    Case(
        id="rm after a sequence inside a substitution on master still blocked",
        make_payload=lambda r: _bash("echo $(true; rm foo.py)", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=(BLOCK_FILE_MOD,),
    ),
    # GNU accepts `--ref` (any unambiguous prefix of `--reference`), and then
    # every operand is a file.
    Case(
        id="chown --ref prefix keeps its first operand as a target",
        make_payload=lambda r: _bash(
            f"chown --ref={r['feat']}/foo.py {r['master']}/foo.py", cwd=r["feat"]
        ),
        expect_exit=2,
        stderr_contains=(BLOCK_FILE_MOD,),
    ),
    Case(
        id="cd then chown --ref on a relative master file blocked",
        make_payload=lambda r: _bash(f"cd {r['master']} && chown --ref=x foo.py", cwd=r["feat"]),
        expect_exit=2,
        stderr_contains=(BLOCK_FILE_MOD,),
    ),
    Case(
        id="chmod --refer prefix keeps its first operand as a target",
        make_payload=lambda r: _bash(f"cd {r['master']} && chmod --refer=x 755", cwd=r["feat"]),
        expect_exit=2,
        stderr_contains=(BLOCK_FILE_MOD,),
    ),
    # === A statement that starts with git still has its redirects and its
    # other pipeline stages judged as file writes. ===
    *(
        Case(
            id=f"git statement with a write on master blocked: {cmd}",
            make_payload=lambda r, cmd=cmd: _bash(cmd, cwd=r["master"]),
            expect_exit=2,
            stderr_contains=(BLOCK_FILE_MOD,),
        )
        for cmd in (
            "git show HEAD:foo.py > foo.py",
            "git ls-files | xargs rm",
            "git ls-files | xargs perl -pi -e 's/a/b/'",
            "git diff | tee foo.py",
        )
    ),
    Case(
        id="git commit as a later pipeline stage on master blocked",
        make_payload=lambda r: _bash("echo x | git commit -F -", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=(BLOCK_COMMIT,),
    ),
    Case(
        id="git log piped to head on master allowed",
        make_payload=lambda r: _bash("git log --oneline | head -5", cwd=r["master"]),
        expect_exit=0,
    ),
    Case(
        id="git diff redirected outside any repo from master allowed",
        make_payload=lambda r: _bash(f"git diff > {r['outside']}/x.patch", cwd=r["master"]),
        expect_exit=0,
    ),
    # === A writer in a later pipeline stage is judged by its own targets, and
    # `|&` and a control `&` end a stage like `|` does. ===
    Case(
        id="later-stage rm into a master repo from a feat cwd blocked",
        make_payload=lambda r: _bash(f"echo y | rm {r['master']}/foo.py", cwd=r["feat"]),
        expect_exit=2,
        stderr_contains=(BLOCK_FILE_MOD,),
    ),
    Case(
        id="later-stage recursive delete of a master repo from a feat cwd blocked",
        make_payload=lambda r: _bash(f"true | rm -rf {r['master']}", cwd=r["feat"]),
        expect_exit=2,
        stderr_contains=(BLOCK_FILE_MOD,),
    ),
    Case(
        id="later-stage rm into a feat repo from a master cwd allowed",
        make_payload=lambda r: _bash(f"echo y | rm {r['feat']}/foo.py", cwd=r["master"]),
        expect_exit=0,
    ),
    *(
        Case(
            id=f"writer after |& or & on master blocked: {cmd}",
            make_payload=lambda r, cmd=cmd: _bash(cmd, cwd=r["master"]),
            expect_exit=2,
            stderr_contains=(BLOCK_FILE_MOD,),
        )
        for cmd in (
            "cat foo.py |& rm foo.py",
            "cat foo.py |& wget -O foo.py http://x",
            "cat foo.py |& truncate -s0 foo.py",
            "echo x & rm foo.py",
        )
    ),
    *(
        Case(
            id=f"force push after |& or & blocked: {cmd}",
            make_payload=lambda r, cmd=cmd: _bash(cmd, cwd=r["feat"]),
            expect_exit=2,
            stderr_contains=("Force push",),
        )
        for cmd in (
            "echo x |& git push --force origin feat",
            "echo x & git push --force origin feat",
        )
    ),
    Case(
        id="git commit after a control & on master blocked",
        make_payload=lambda r: _bash("echo x & git commit -m x", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=(BLOCK_COMMIT,),
    ),
    # === More in-place spellings: BSD `-I`, `gsed`, GNU long-option prefixes,
    # perl's `-g`, and a flag written inside quotes. ===
    *(
        Case(
            id=f"in-place spelling on master blocked: {cmd}",
            make_payload=lambda r, cmd=cmd: _bash(cmd, cwd=r["master"]),
            expect_exit=2,
            stderr_contains=(BLOCK_FILE_MOD,),
        )
        for cmd in (
            "sed -I '' 's/a/b/' foo.py",
            "gsed -i 's/a/b/' foo.py",
            "sed --i 's/a/b/' foo.py",
            "sed --in 's/a/b/' foo.py",
            "perl -gpi -e 's/a/b/' foo.py",
            "sed \"-i\" 's/a/b/' foo.py",
            "sed '-i' 's/a/b/' foo.py",
            "perl '-pi' -e 's/a/b/' foo.py",
        )
    ),
    Case(
        id="sed program text containing -i on master allowed",
        make_payload=lambda r: _bash("sed -n 's/ -i/x/p' foo.txt", cwd=r["master"]),
        expect_exit=0,
    ),
    Case(
        id="quoted force flag on git push blocked",
        make_payload=lambda r: _bash("git push '-f' origin feat", cwd=r["feat"]),
        expect_exit=2,
        stderr_contains=("Force push",),
    ),
    # === Destructive commands with a pipeline around them stay blocked. ===
    Case(
        id="git clean -fdx piped to grep blocked",
        make_payload=lambda r: _bash("git clean -fdx 2>&1 | grep -n x", cwd=r["feat"]),
        expect_exit=2,
        stderr_contains=("git clean -f",),
    ),
    Case(
        id="force push as a later pipeline stage blocked",
        make_payload=lambda r: _bash("echo x | git push --force origin feat", cwd=r["feat"]),
        expect_exit=2,
        stderr_contains=("Force push",),
    ),
    # === cp, ln, and install write only their destination: the last operand,
    # or the `-t`/`--target-directory` value. A source in a protected repo is
    # only read. When the options cannot be parsed, every operand is judged. ===
    *(
        Case(
            id=f"copy-like command reading a master file allowed: {cmd_id}",
            make_payload=lambda r, cmd=cmd: _bash(cmd(r), cwd=r["feat"]),
            expect_exit=0,
        )
        for cmd_id, cmd in (
            ("cp src dst", lambda r: f"cp {r['master']}/foo.py {r['outside']}/foo.py"),
            ("cp -t dir src", lambda r: f"cp -t {r['outside']} {r['master']}/foo.py"),
            ("ln -s target link", lambda r: f"ln -s {r['master']}/foo.py {r['outside']}/link"),
            (
                "install -m 755",
                lambda r: f"install -m 755 {r['master']}/foo.py {r['outside']}/foo",
            ),
            (
                "install -o -g",
                lambda r: f"install -o nate -g staff {r['master']}/foo.py {r['outside']}/foo",
            ),
        )
    ),
    *(
        Case(
            id=f"copy-like command writing into master blocked: {cmd_id}",
            make_payload=lambda r, cmd=cmd: _bash(cmd(r), cwd=r["feat"]),
            expect_exit=2,
            stderr_contains=(BLOCK_FILE_MOD,),
        )
        for cmd_id, cmd in (
            ("cp src dst", lambda r: f"cp {r['outside']}/x {r['master']}/foo.py"),
            ("cp many srcs", lambda r: f"cp {r['outside']}/a {r['outside']}/b {r['master']}"),
            ("cp -t", lambda r: f"cp -t {r['master']} {r['outside']}/x"),
            ("cp -tDIR", lambda r: f"cp -t{r['master']} {r['outside']}/x"),
            (
                "cp --target-directory=",
                lambda r: f"cp --target-directory={r['master']} {r['outside']}/x",
            ),
            (
                "cp --target-directory DIR",
                lambda r: f"cp --target-directory {r['master']} {r['outside']}/x",
            ),
            ("cp --target abbreviation", lambda r: f"cp --target {r['master']} {r['outside']}/x"),
            ("cp -S suffix", lambda r: f"cp -S .bak {r['outside']}/x {r['master']}/foo.py"),
            ("ln -s target link", lambda r: f"ln -s {r['outside']}/x {r['master']}/link"),
            ("ln -s one operand", lambda r: f"cd {r['master']} && ln -s {r['outside']}/x"),
            (
                "install -m",
                lambda r: f"install -m 755 {r['outside']}/x {r['master']}/foo.py",
            ),
            ("install -m0755", lambda r: f"install -m0755 {r['outside']}/x {r['master']}/foo.py"),
            ("install -d", lambda r: f"install -d {r['outside']}/a {r['master']}/newdir"),
            (
                "install unknown -B",
                lambda r: f"install -B .bak {r['master']}/foo.py {r['outside']}/y",
            ),
            ("cp unparsable single operand", lambda r: f"cd {r['master']} && cp foo.py"),
        )
    ),
    # === A heredoc body is data unless a shell runs it, so its lines are not
    # read as commands. The command that opens the heredoc is still judged. ===
    *(
        Case(
            id=f"heredoc body read as data allowed: {cmd_id}",
            make_payload=lambda r, cmd=cmd, cwd=cwd: _bash(cmd(r), cwd=r[cwd]),
            expect_exit=0,
        )
        for cmd_id, cwd, cmd in (
            (
                "gitignored target on master",
                "master",
                lambda _r: (
                    "cat > ignored_dir/x.md <<'EOF'\nrm -rf foo.py\nsed -i s/a/b/ foo.py\nEOF"
                ),
            ),
            (
                "target outside any repo",
                "master",
                lambda r: f"cat > {r['outside']}/x.md <<'EOF'\nrm foo.py\nEOF",
            ),
            (
                "unquoted tag with no substitution",
                "master",
                lambda r: f"cat <<EOF > {r['outside']}/x.md\nchmod +x foo.py\nEOF",
            ),
            (
                "destructive text in a note",
                "feat",
                lambda r: f"cat > {r['outside']}/n.md <<'EOF'\ngit push --force\nEOF",
            ),
        )
    ),
    *(
        Case(
            id=f"heredoc still judged blocked: {cmd_id}",
            make_payload=lambda r, cmd=cmd: _bash(cmd(r), cwd=r["master"]),
            expect_exit=2,
            stderr_contains=(BLOCK_FILE_MOD,),
        )
        for cmd_id, cmd in (
            ("redirect into a tracked file", lambda _r: "cat > foo.py <<'EOF'\nprint(1)\nEOF"),
            ("body run by bash", lambda _r: "bash <<'EOF'\nrm foo.py\nEOF"),
            ("body run by sudo sh -s", lambda _r: "sudo sh -s <<'EOF'\nrm foo.py\nEOF"),
            ("body piped into bash", lambda _r: "cat <<'EOF' | bash\nrm foo.py\nEOF"),
            (
                "command after the delimiter",
                lambda r: f"cat > {r['outside']}/x <<'EOF'\nhi\nEOF\nrm foo.py",
            ),
        )
    ),
    Case(
        id="heredoc body run by bash with a force push blocked",
        make_payload=lambda r: _bash(
            "bash <<'EOF'\ngit push --force origin feat\nEOF", cwd=r["feat"]
        ),
        expect_exit=2,
        stderr_contains=("Force push",),
    ),
    Case(
        id="heredoc body run by sudo -u bob bash blocked",
        make_payload=lambda r: _bash("sudo -u bob bash <<'EOF'\nrm foo.py\nEOF", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=(BLOCK_FILE_MOD,),
    ),
    Case(
        id="heredoc body run by a quoted bash path blocked",
        make_payload=lambda r: _bash("'/bin/bash' <<'EOF'\nrm foo.py\nEOF", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=(BLOCK_FILE_MOD,),
    ),
    # === cp/ln/install: fd duplications, input redirects, and comments are not
    # operands, and a destination that expands (`$VAR`, `$( )`, backticks) is
    # not trusted, so every operand is judged. ===
    *(
        Case(
            id=f"copy destination with trailing shell syntax blocked: {suffix}",
            make_payload=lambda r, cmd=cmd, suffix=suffix: _bash(
                f"{cmd} {r['outside']}/x {r['master']}/foo.py {suffix}", cwd=r["feat"]
            ),
            expect_exit=2,
            stderr_contains=(BLOCK_FILE_MOD,),
        )
        for cmd, suffix in (
            ("cp", "2>&1"),
            ("cp", "2>&1 | tail -1"),
            ("ln -sf", "2>&1"),
            ("install -m 644", "2>&1"),
            ("cp", ">&2"),
            ("cp", "< /dev/null"),
            ("cp", "</dev/null"),
            ("cp", "<<< hi"),
            ("cp", "# copy it"),
            ("cp", "$(true)"),
            ("cp", "`true`"),
            ("cp", "$UNSET_VAR"),
        )
    ),
    Case(
        id="unknown long option on cp judges every operand",
        make_payload=lambda r: _bash(
            f"cp --frobnicate {r['master']}/foo.py {r['outside']}/x", cwd=r["feat"]
        ),
        expect_exit=2,
        stderr_contains=(BLOCK_FILE_MOD,),
    ),
    Case(
        id="cp --strip prefix of a valueless option on master target blocked",
        make_payload=lambda r: _bash(
            f"cp --strip {r['outside']}/x {r['master']}/foo.py", cwd=r["feat"]
        ),
        expect_exit=2,
        stderr_contains=(BLOCK_FILE_MOD,),
    ),
    Case(
        id="fd dup is not a path for rm on master",
        make_payload=lambda r: _bash("rm /tmp/nothing-here 2>&1", cwd=r["master"]),
        expect_exit=0,
    ),
    Case(
        id="fd dup is not a path for cp out of master",
        make_payload=lambda r: _bash(f"cp foo.py {r['outside']}/y 2>&1", cwd=r["master"]),
        expect_exit=0,
    ),
    Case(
        id="cp into a tracked file with a comment on master blocked",
        make_payload=lambda r: _bash(f"cp {r['outside']}/x foo.py # c", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=(BLOCK_FILE_MOD,),
    ),
    # === A heredoc body is dropped only for a known data sink (a lone `cat` or
    # `tee`, a non-shell interpreter, a commit/PR message command). Any other
    # consumer may run it as shell, so its body is judged. ===
    *(
        Case(
            id=f"heredoc body fed to a possible shell blocked: {cmd!r}",
            make_payload=lambda r, cmd=cmd: _bash(cmd, cwd=r["master"]),
            expect_exit=2,
            stderr_contains=(BLOCK_FILE_MOD,),
        )
        for cmd in (
            "cat <<'EOF'|sh\nrm foo.py\nEOF",
            "cat <<'EOF' |\nrm foo.py\nEOF\nsh",
            "sudo -s <<'EOF'\nrm foo.py\nEOF",
            "su <<'EOF'\nrm foo.py\nEOF",
            "script -q /dev/null <<'EOF'\nrm foo.py\nEOF",
            "csh <<'EOF'\nrm foo.py\nEOF",
            "tcsh <<'EOF'\nrm foo.py\nEOF",
            "$SHELL <<'EOF'\nrm foo.py\nEOF",
            "\"$SHELL\" -s <<'EOF'\nrm foo.py\nEOF",
            "eval $(cat <<'EOF'\nrm foo.py\nEOF\n)",
            "exec 3<<'EOF'\nrm foo.py\nEOF\nsh <&3",
            "cat <<'EOF' > /tmp/s.sh && sh /tmp/s.sh\nrm foo.py\nEOF",
            "cat > /tmp/s.sh <<'EOF'\nrm foo.py\nEOF\nbash /tmp/s.sh",
            "ssh localhost <<'EOF'\nrm foo.py\nEOF",
        )
    ),
    *(
        Case(
            id=f"heredoc body fed to a data sink allowed: {cmd!r}",
            make_payload=lambda r, cmd=cmd: _bash(cmd, cwd=r["master"]),
            expect_exit=0,
        )
        for cmd in (
            "cat > /tmp/n.md <<'EOF'\nrm -rf foo.py\nEOF",
            "cat <<'EOF' > /tmp/n.md\nit's sed -i\nEOF",
            "tee /tmp/n.md <<'EOF' >/dev/null\nrm foo.py\nEOF",
            "python3 - <<'EOF'\nrm foo.py\nEOF",
        )
    ),
    Case(
        id="heredoc to cat with a &> redirect on master allowed",
        make_payload=lambda r: _bash("cat <<'EOF' &>/tmp/n.md\nrm foo.py\nEOF", cwd=r["master"]),
        expect_exit=0,
    ),
    # === Command substitutions (`$( )`, backticks, `<( )`) run their bodies, so
    # each body is judged as a command, also inside double quotes and inside an
    # unquoted heredoc body. Only the substitution of a data heredoc runs. ===
    *(
        Case(
            id=f"write in a substitution on master blocked: {cmd!r}",
            make_payload=lambda r, cmd=cmd: _bash(cmd, cwd=r["master"]),
            expect_exit=2,
            stderr_contains=(BLOCK_FILE_MOD,),
        )
        for cmd in (
            'echo "$(rm foo.py)"',
            "echo `rm foo.py`",
            'echo "x $(sed -i s/a/b/ foo.py)"',
            "diff <(rm foo.py) /dev/null",
            "echo $(( $(rm foo.py) + 1 ))",
            "cd $(rm foo.py; echo .)",
            "cat > /tmp/x <<EOF\n$(rm foo.py)\nEOF",
            "cat > /tmp/x <<EOF\n`rm foo.py`\nEOF",
            "cat > /tmp/x <<EOF\nhi $(rm foo.py)\nEOF",
            "cat > /tmp/x <<EOF\nit's $(rm foo.py)\nEOF",
            "eval \"$(cat <<'EOF'\nrm foo.py\nEOF\n)\"",
            "$(cat <<'EOF'\nrm foo.py\nEOF\n)",
        )
    ),
    Case(
        id="force push in a substitution blocked",
        make_payload=lambda r: _bash("echo $(git push --force origin feat)", cwd=r["feat"]),
        expect_exit=2,
        stderr_contains=("Force push",),
    ),
    *(
        Case(
            id=f"substitution that only reads on master allowed: {cmd_id}",
            make_payload=lambda r, cmd=cmd: _bash(cmd(r), cwd=r["master"]),
            expect_exit=0,
        )
        for cmd_id, cmd in (
            ("branch name", lambda _r: "echo $(git branch --show-current)"),
            ("single-quoted text", lambda _r: "echo '$(rm foo.py)'"),
            (
                "data heredoc with a harmless substitution",
                lambda r: f"cat > {r['outside']}/x <<EOF\n$(date)\nrm foo.py\nEOF",
            ),
            (
                "commit message heredoc into a feat repo",
                lambda r: (
                    f"git -C {r['feat']} commit -m \"$(cat <<'EOF'\nfix: x\n\n"
                    "rm -rf foo.py and sed -i stuff, it's fine\nEOF\n)\""
                ),
            ),
            (
                "PR body heredoc",
                lambda _r: "gh pr create --title x --body \"$(cat <<'EOF'\nrm foo.py\nEOF\n)\"",
            ),
        )
    ),
    Case(
        id="assignment of a message heredoc substitution on master allowed",
        make_payload=lambda r: _bash(
            "MSG=$(cat <<'EOF'\nrm foo.py, it's done\nEOF\n)", cwd=r["master"]
        ),
        expect_exit=0,
    ),
    Case(
        id="cp destination printed by a substitution into master blocked",
        make_payload=lambda r: _bash(
            f"cp {r['outside']}/x $(echo {r['master']}/foo.py)", cwd=r["feat"]
        ),
        expect_exit=2,
        stderr_contains=(BLOCK_FILE_MOD,),
    ),
    # === A control `&` ends a statement, so a `cd` after a background job moves
    # the effective cwd. A backgrounded `cd`, or one in a pipeline, runs in a
    # subshell and moves nothing. ===
    *(
        Case(
            id=f"cd after a background job into master blocked: {cmd_id}",
            make_payload=lambda r, cmd=cmd: _bash(cmd(r), cwd=r["feat"]),
            expect_exit=2,
            stderr_contains=("BLOCKED [branch-protection]",),
        )
        for cmd_id, cmd in (
            ("rm", lambda r: f"echo x & cd {r['master']} && rm foo.py"),
            ("rm after ;", lambda r: f"sleep 1 & cd {r['master']}; rm foo.py"),
            ("sed -i", lambda r: f"sleep 1 & cd {r['master']} && sed -i 's/a/b/' foo.py"),
            ("commit", lambda r: f"sleep 1 & cd {r['master']} && git commit -m x"),
            ("no space", lambda r: f"echo x &cd {r['master']} && rm foo.py"),
        )
    ),
    *(
        Case(
            id=f"cd in a subshell does not move the cwd: {cmd_id}",
            make_payload=lambda r, cmd=cmd: _bash(cmd(r), cwd=r["feat"]),
            expect_exit=0,
        )
        for cmd_id, cmd in (
            ("backgrounded cd", lambda r: f"cd {r['master']} & rm foo.py"),
            ("cd in a pipeline", lambda r: f"cd {r['master']} | rm foo.py"),
        )
    ),
    *(
        Case(
            id=f"quoted force refspec blocked: {cmd}",
            make_payload=lambda r, cmd=cmd: _bash(cmd, cwd=r["feat"]),
            expect_exit=2,
            stderr_contains=("Force push via refspec",),
        )
        for cmd in ("git push origin '+feat'", 'git push origin "+feat:feat"')
    ),
    # === git subcommands that rewrite or remove tracked files in the working
    # tree are file writes on a protected branch. Index-only, dry-run, and
    # read-only forms are not. ===
    *(
        Case(
            id=f"git working-tree write on master blocked: {cmd}",
            make_payload=lambda r, cmd=cmd: _bash(cmd, cwd=r["master"]),
            expect_exit=2,
            stderr_contains=(BLOCK_FILE_MOD,),
        )
        for cmd in (
            "git rm foo.py",
            "git rm -r src",
            "git mv foo.py bar.py",
            "git checkout HEAD -- foo.py",
            "git checkout -- foo.py",
            "git restore foo.py",
            "git restore --source=HEAD~1 foo.py",
            "git restore -W foo.py",
            "git restore --staged --worktree foo.py",
        )
    ),
    *(
        Case(
            id=f"git index-only or read-only form on master allowed: {cmd!r}",
            make_payload=lambda r, cmd=cmd: _bash(cmd, cwd=r["master"]),
            expect_exit=0,
        )
        for cmd in (
            "git restore --staged foo.py",
            "git rm --cached foo.py",
            "git rm -n foo.py",
            "git rm --dry-run foo.py",
            "git mv -n foo.py bar.py",
            "git stash list",
            "git stash show -p",
            # Stashing parks uncommitted edits where they stay recoverable, which is
            # how stray work moves off trunk; only pop and apply write the tree.
            "git stash",
            "git stash push -m x",
            "git stash -u",
            "git stash save x",
            "git checkout feat",
            "git commit --dry-run -m x",
            "git commit --dry-run -F - <<'EOF'\nmsg\nEOF",
        )
    ),
    Case(
        id="git rm in a feat repo allowed",
        make_payload=lambda r: _bash("git rm foo.py", cwd=r["feat"]),
        expect_exit=0,
    ),
)


def _run_hook(
    hooks_dir: Path,
    payload: Payload,
    home: str,
    *,
    exempt: str | None = None,
    project_dir: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Pipe `payload` through the PreToolUse dispatcher, optionally declaring an exempt root.

    Strips leaked git-location vars (GIT_DIR, ...) so the hook resolves the
    ephemeral test repos, not the checkout the suite runs from (pre-commit /
    worktree set these, which would otherwise hijack branch detection). `home`
    and `project_dir` pin both config layers, so no file outside the test
    decides what the hook allows.
    """
    env = clean_environ()
    env["HOME"] = home
    env.pop("CLAUDE_PROJECT_DIR", None)
    if project_dir is not None:
        env["CLAUDE_PROJECT_DIR"] = project_dir
    if exempt is not None:
        env.update(exempt_env(exempt))
    return subprocess.run(
        [str(hooks_dir / "pretooluse.py")],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
        env=env,
    )


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_enforce_branch_protection(
    case: Case,
    repos: Mapping[str, str],
    hooks_dir: Path,
    empty_home: str,
) -> None:
    """Verify the hook blocks or allows each action per its rules."""
    # Given a payload built against the ephemeral repos
    payload = case.make_payload(repos)

    # When invoking the hook with the payload on stdin
    proc = _run_hook(hooks_dir, payload, empty_home)

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


@pytest.mark.parametrize(
    ("clause", "expected_head"),
    [
        ("rm foo.py", "rm"),  # no prefix
        ("sudo rm foo.py", "rm"),  # launcher
        ("sudo -E rm foo.py", "rm"),  # launcher with a valueless flag
        ("/bin/rm foo.py", "rm"),  # absolute path -> basename
        ("/usr/bin/env rm foo.py", "rm"),  # path-launcher then command
        ("command rm foo.py", "rm"),  # builtin launcher
        ("FOO=bar rm foo.py", "rm"),  # env-assignment prefix
        ("cat foo.py", "cat"),  # non-wrapper passes through
    ],
)
def test_command_index_resolves_real_executable(
    hooks_dir: Path, clause: str, expected_head: str
) -> None:
    """Verify the real executable is found past launchers, env-assignments, and paths."""
    # Given the clause tokenized into whitespace word-spans
    m = _load_hook(hooks_dir)
    spans = list(re.finditer(r"\S+", clause))

    # When resolving the command index
    idx = m._command_index(spans)

    # Then the token at that index basenames to the expected executable
    head = spans[idx].group().lstrip("\\").rsplit("/", 1)[-1]
    assert head == expected_head


def test_command_index_returns_len_when_no_command(hooks_dir: Path) -> None:
    """Verify a clause that is only launchers/assignments yields no executable index."""
    # Given a bare launcher and a lone env-assignment
    m = _load_hook(hooks_dir)
    for clause in ("sudo", "FOO=bar"):
        spans = list(re.finditer(r"\S+", clause))
        # Then the index is past the last span (no real command found)
        assert m._command_index(spans) == len(spans)


def test_command_index_known_gap_launcher_flag_value(hooks_dir: Path) -> None:
    """Verify a launcher flag that takes a separate value is a documented gap."""
    # Given `sudo -u bob rm`: only valueless launcher flags are skipped, so the
    # flag's value `bob` is mistaken for the command rather than `rm`.
    m = _load_hook(hooks_dir)
    spans = list(re.finditer(r"\S+", "sudo -u bob rm foo.py"))

    # Then the resolved head is the flag value, not rm -- the known limitation
    assert spans[m._command_index(spans)].group() == "bob"


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
    # No exempt roots: these cases are about the branch/gitignore predicate,
    # and the exemption has its own suite.
    none_exempt = m.exempt_paths.ExemptRoots()

    # Then a target outside any repo is exempt -- a /tmp scratch path or a `..`
    # that resolves out of every repo both yield "" from the branch lookup
    assert m._target_protected_branch("/tmp/x", "", none_exempt) is None  # noqa: S108
    assert m._target_protected_branch("/tmp/../tracked.txt", "", none_exempt) is None  # noqa: S108
    assert m._target_protected_branch("/external/store/x.md", "", none_exempt) is None
    assert m._target_protected_branch("x.md", "/external/store", none_exempt) is None

    # Then on a protected branch only gitignored targets are exempt: an absolute
    # gitignored target passes with no cwd, an absolute tracked one does not
    # (cwd is only needed to resolve relative paths)
    assert m._target_protected_branch(f"{base}/ignored_dir/x", "", none_exempt) is None
    assert m._target_protected_branch(f"{base}/foo.py", "", none_exempt) == "master"

    # Then a relative target with a cwd resolves and is judged (gitignored here,
    # so exempt). With no cwd it can't be located, so it can't be attributed to a
    # protected branch and is treated as harmless (the fail-open default).
    assert m._target_protected_branch("ignored_dir/x", base, none_exempt) is None
    assert m._target_protected_branch("ignored_dir/x", "", none_exempt) is None


def test_target_protected_branch_follows_symlink_into_protected_repo(
    repos: Mapping[str, str], hooks_dir: Path, tmp_path: Path
) -> None:
    """Verify a symlink resolving into a protected repo is judged by its real path."""
    # Given a symlink that lives outside any repo but points at a tracked path
    # inside the master repo, which is on a protected branch. The predicate runs
    # git in-process, so it depends on the suite-wide fixture having cleared every
    # GIT_-prefixed var; a leaked one would hijack branch detection to the outer
    # checkout.
    m = _load_hook(hooks_dir)
    link = tmp_path / "sneaky.py"
    link.symlink_to(Path(repos["master"]) / "app.py")

    # When checking the symlink target while the repo is on a protected branch
    # Then the branch lookup follows the link to the in-repo path and blocks it,
    # rather than reading the link's own (repo-less) parent directory as exempt
    assert m._target_protected_branch(str(link), "", m.exempt_paths.ExemptRoots()) == "master"


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


# === Exempt-path carve-out ==================================================


@dataclass(frozen=True)
class ExemptCase:
    """One case run with the `exempt` repo declared an exempt root."""

    id: str
    make_payload: Callable[[Mapping[str, str]], Payload]
    expect_exit: int
    stderr_contains: tuple[str, ...] = ()


EXEMPT_CASES: tuple[ExemptCase, ...] = (
    # Protected-branch checks do not apply inside an exempt tree: those are
    # working stores committed to on their default branch by design.
    ExemptCase(
        id="edit in the exempt repo allowed",
        make_payload=lambda r: _edit(f"{r['exempt']}/foo.py"),
        expect_exit=0,
    ),
    ExemptCase(
        id="write in the exempt repo allowed",
        make_payload=lambda r: _write(f"{r['exempt']}/new.py"),
        expect_exit=0,
    ),
    ExemptCase(
        id="notebook edit in the exempt repo allowed",
        make_payload=lambda r: _notebook(f"{r['exempt']}/foo.ipynb"),
        expect_exit=0,
    ),
    ExemptCase(
        id="commit from inside the exempt repo allowed",
        make_payload=lambda r: _bash('git commit -m "feat: add note"', cwd=r["exempt"]),
        expect_exit=0,
    ),
    ExemptCase(
        id="git -C into the exempt repo commit allowed",
        make_payload=lambda r: _bash(
            f'git -C {r["exempt"]} commit -m "feat: add note"', cwd=r["outside"]
        ),
        expect_exit=0,
    ),
    ExemptCase(
        id="cd into the exempt repo then commit allowed",
        make_payload=lambda r: _bash(
            f'cd {r["exempt"]} && git commit -m "feat: add note"', cwd=r["outside"]
        ),
        expect_exit=0,
    ),
    ExemptCase(
        id="merge in the exempt repo does not ask",
        make_payload=lambda r: _bash("git merge feature", cwd=r["exempt"]),
        expect_exit=0,
    ),
    ExemptCase(
        id="git stash pop in the exempt repo allowed",
        make_payload=lambda r: _bash("git stash pop", cwd=r["exempt"]),
        expect_exit=0,
    ),
    ExemptCase(
        id="rm targeting the exempt repo from outside allowed",
        make_payload=lambda r: _bash(f"rm {r['exempt']}/foo.py", cwd=r["outside"]),
        expect_exit=0,
    ),
    ExemptCase(
        id="unconfinable write from an exempt cwd allowed",
        make_payload=lambda r: _bash("sed -i s/a/b/ foo.py", cwd=r["exempt"]),
        expect_exit=0,
    ),
    ExemptCase(
        id="unconfinable write from a master cwd still blocked",
        make_payload=lambda r: _bash("sed -i s/a/b/ foo.py", cwd=r["master"]),
        expect_exit=2,
        stderr_contains=("Cannot modify files",),
    ),
    # The carve-out is scoped to the exempt tree, not to protected branches at
    # large: another repo on master is still guarded while one is configured.
    ExemptCase(
        id="edit in another master repo still blocked",
        make_payload=lambda r: _edit(f"{r['master']}/foo.py"),
        expect_exit=2,
        stderr_contains=(BLOCK_FILE_MOD,),
    ),
    ExemptCase(
        id="rm targeting another master repo from an exempt cwd still blocked",
        make_payload=lambda r: _bash(f"rm {r['master']}/foo.py", cwd=r["exempt"]),
        expect_exit=2,
        stderr_contains=(BLOCK_FILE_MOD,),
    ),
    ExemptCase(
        id="commit into another master repo from an exempt cwd still blocked",
        make_payload=lambda r: _bash(f'git -C {r["master"]} commit -m "feat: x"', cwd=r["exempt"]),
        expect_exit=2,
        stderr_contains=(BLOCK_COMMIT,),
    ),
    # Destructive commands stay blocked inside an exempt tree: they destroy
    # work whatever branch they run on, so the carve-out never reaches them.
    ExemptCase(
        id="force push in the exempt repo still blocked",
        make_payload=lambda r: _bash("git push --force origin master", cwd=r["exempt"]),
        expect_exit=2,
        stderr_contains=("Force push",),
    ),
    ExemptCase(
        id="reset --hard in the exempt repo still blocked",
        make_payload=lambda r: _bash("git reset --hard HEAD~1", cwd=r["exempt"]),
        expect_exit=2,
        stderr_contains=("reset --hard",),
    ),
    ExemptCase(
        id="clean -fd in the exempt repo still blocked",
        make_payload=lambda r: _bash("git clean -fd", cwd=r["exempt"]),
        expect_exit=2,
        stderr_contains=("git clean -f",),
    ),
)


@pytest.mark.parametrize("case", EXEMPT_CASES, ids=lambda c: c.id)
def test_exempt_path_carve_out(
    case: ExemptCase,
    repos: Mapping[str, str],
    hooks_dir: Path,
    empty_home: str,
) -> None:
    """Verify an exempt root waives protected-branch checks but not destructive ones."""
    # Given the exempt repo declared an exempt root
    payload = case.make_payload(repos)

    # When invoking the hook with the payload on stdin
    proc = _run_hook(hooks_dir, payload, empty_home, exempt=repos["exempt"])

    # Then exit code and stderr match expectations
    diag = f"\n  stderr={proc.stderr!r}\n  stdout={proc.stdout!r}"
    assert proc.returncode == case.expect_exit, f"exit={proc.returncode}{diag}"
    for s in case.stderr_contains:
        assert s in proc.stderr, f"missing {s!r} in stderr{diag}"
    # An ASK also exits 0, so an allowed case must additionally carry no
    # permission decision -- otherwise the merge case would pass while still
    # prompting. Advisory-only output has no `permissionDecision` key.
    if case.expect_exit == 0:
        assert "permissionDecision" not in proc.stdout, f"unexpected permission prompt{diag}"


@pytest.mark.parametrize(
    ("exempt_value", "case"),
    [("", "empty"), ("relative/store", "relative"), ("/", "filesystem root")],
)
def test_exempt_path_unusable_value_still_blocks(
    repos: Mapping[str, str], hooks_dir: Path, empty_home: str, exempt_value: str, case: str
) -> None:
    """Verify a variable that cannot name one tree exempts nothing."""
    # Given an exemption variable whose value resolves to no usable root
    payload = _edit(f"{repos['exempt']}/foo.py")

    # When editing a file on a protected branch
    proc = _run_hook(hooks_dir, payload, empty_home, exempt=exempt_value)

    # Then the edit is still blocked
    assert proc.returncode == 2, f"{case}: exit={proc.returncode} stderr={proc.stderr!r}"
    assert BLOCK_FILE_MOD in proc.stderr, case


def _write_toml(claude_dir: Path, exempt: str) -> None:
    """Write a toolkit config declaring `exempt` an exempt tree."""
    claude_dir.mkdir(parents=True, exist_ok=True)
    (claude_dir / "natelandau-toolkit.toml").write_text(
        f'exempt_paths = ["{exempt}"]\n', encoding="utf-8"
    )


def test_exempt_path_from_the_global_config(
    repos: Mapping[str, str], hooks_dir: Path, tmp_path: Path
) -> None:
    """Verify a root declared in the global config waives the protected-branch check."""
    # Given a global config exempting the repo, and no exemption variable
    home = tmp_path / "home"
    _write_toml(home / ".claude", repos["exempt"])

    # When editing a file in that repo while it sits on a protected branch
    proc = _run_hook(hooks_dir, _edit(f"{repos['exempt']}/foo.py"), str(home))

    # Then the edit passes
    assert proc.returncode == 0, f"stderr={proc.stderr!r}"


def test_exempt_path_in_a_project_config_is_ignored(
    hooks_dir: Path, empty_home: str, tmp_path: Path
) -> None:
    """Verify a repo's own committed config cannot exempt that repo.

    The project config layer is a file inside the repository the guard protects,
    and it is committed, so honoring `exempt_paths` there would let one repo
    disable the guard for everyone who clones it.
    """
    # Given a repo on a protected branch whose own .claude config exempts itself
    project = tmp_path / "self_exempting"
    project.mkdir()
    env = clean_environ()
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(project)], check=True, capture_output=True, env=env
    )
    _write_toml(project / ".claude", str(project))

    # When editing a file in it with that repo as the project dir
    proc = _run_hook(hooks_dir, _edit(f"{project}/foo.py"), empty_home, project_dir=str(project))

    # Then the edit is still blocked
    assert proc.returncode == 2, f"stderr={proc.stderr!r}"
    assert "Cannot modify files on the 'main' branch" in proc.stderr


# === Tilde paths ============================================================


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("rm ~/master_repo/foo.py", BLOCK_FILE_MOD),
        ('cd ~/master_repo && git commit -m "feat: x"', BLOCK_COMMIT),
        ('git -C ~/master_repo commit -m "feat: x"', BLOCK_COMMIT),
    ],
)
def test_tilde_paths_are_expanded_before_the_branch_lookup(
    repos: Mapping[str, str], hooks_dir: Path, command: str, expected: str
) -> None:
    """Verify a `~`-written path is judged by the repo it names, not by the cwd.

    The hook reads the command before the shell expands anything, so a tilde
    joined onto the cwd would name a directory outside every repo and the
    branch lookup would report nothing to protect.
    """
    # Given a home directory holding the protected repo
    home = str(Path(repos["master"]).parent)
    payload = _bash(command, cwd=repos["outside"])

    # When invoking the hook from an unrelated cwd
    proc = _run_hook(hooks_dir, payload, home)

    # Then the action is blocked exactly as its absolute spelling would be
    assert proc.returncode == 2, f"stderr={proc.stderr!r}"
    assert expected in proc.stderr


def test_an_unusable_exempt_entry_does_not_disable_the_hook(
    repos: Mapping[str, str], hooks_dir: Path, empty_home: str
) -> None:
    """Verify a tilde entry naming no account drops itself rather than the guard.

    Every entry is resolved before any check runs, so an entry that raises
    while expanding would take the whole hook down with it and silently allow
    every protected-branch action.
    """
    # Given an exemption variable naming an account that does not exist
    payload = _edit(f"{repos['master']}/foo.py")

    # When editing a file on a protected branch
    proc = _run_hook(hooks_dir, payload, empty_home, exempt="~nosuchuser42/store")

    # Then the edit is still blocked
    assert proc.returncode == 2, f"stderr={proc.stderr!r}"
    assert BLOCK_FILE_MOD in proc.stderr
