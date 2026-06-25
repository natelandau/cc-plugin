#!/usr/bin/env -S uv run --script

# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///

"""PreToolUse hook: blocks destructive git commands and file modifications.

Blocks destructive git operations (force push, hard reset, clean -f, etc.)
on ALL branches, and blocks file modifications on protected branches
(main/master). Supports git worktrees by checking the branch at the actual
target location.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from lib import bash
from lib.io import Decision

if TYPE_CHECKING:
    from lib.config import Config

ID = "branch-protection"
PROTECTED_BRANCHES = {"main", "master"}

# Single hint appended to every protected-branch block message. Both
# file-modifying tools (Edit/Write/NotebookEdit) and file-modifying bash
# commands point at the same remediation, so the text lives in one place.
PROTECTED_BRANCH_HINT = (
    "Create a new branch first:\n"
    "  git checkout -b <branch-name>\n"
    "Or use a worktree for isolated work:\n"
    "  git worktree add .worktrees/<branch-name> -b <branch-name>"
)

# Shown when a merge/pull would write a merge commit onto a protected branch.
# Points at the two forms that land work without creating a merge commit there.
MERGE_COMMIT_HINT = (
    "A merge commit (from `git merge`/`git pull`) writes directly to the "
    "protected branch, which is the same as committing to it. To land work "
    "without a merge commit:\n"
    "  - fast-forward only:  git merge --ff-only <branch>\n"
    "  - or squash-merge:    git merge --squash <branch> && git commit"
)

# `git merge`/`git pull` forms that cannot write a merge commit to the current
# branch: `--ff-only` only fast-forwards (or errors), `--squash` stages without
# committing (its follow-up `git commit` is caught by the commit guard),
# `--abort`/`--quit` cancel an in-progress merge, and `pull --rebase`/`-r`
# replays commits instead of merging. Anything else may create a merge commit.
SAFE_MERGE_RE = re.compile(r"--ff-only\b|--squash\b|--abort\b|--quit\b|--rebase\b|\s-r\b")
MERGE_PULL_RE = re.compile(r"^\s*git\s+(?:merge|pull)\b")

GIT_C_ADVISORY = (
    "WARNING: Avoid using `git -C <path>`. "
    "Check your current working directory and `cd` into the correct "
    "directory first, then run `git` directly. "
    "Only fall back to `git -C` if direct `git` fails."
)
GIT_C_RE = re.compile(r"\bgit\s+-C\b")


@dataclass(frozen=True, slots=True)
class CommandRule:
    r"""Declarative command-matching rule.

    Named `CommandRule` (not `Rule`) to stay distinct from `lib.rules.Rule`,
    the TOML-driven engine the other hooks share. This hook keeps its own
    rule type because its matcher carries `match_full`/`exclude` semantics
    and the bypass logic lives alongside the data in this module.

    `pattern` is a regex tested against each compound sub-part of a command
    by default (split on `&&`, `||`, `;`). Set `match_full=True` to test
    against the entire command string instead -- needed for patterns that
    span operators (e.g. output redirects).

    `reason` is shown to the user when a DESTRUCTIVE rule blocks. For
    PROTECTED_FILE_MOD rules the message is always `PROTECTED_BRANCH_HINT`,
    so `reason` is optional.

    `exclude` is a regex that, if it also matches, negates the rule. Use
    for safe variants (e.g. `--dry-run`).

    Example::

        CommandRule(
            pattern=r"^\\s*git\\s+stash\\s+drop\\b",
            reason="git stash drop permanently discards stashed changes",
        )
    """

    pattern: str
    reason: str = ""
    match_full: bool = False
    exclude: str | None = None


# === RULE DEFINITIONS ===
#
# To add a rule, append a CommandRule(...) to the appropriate tuple below.
# See the CommandRule docstring above for field semantics and a syntax example.
#
# DESTRUCTIVE_RULES        -- blocked on every branch; `reason` is shown.
# PROTECTED_FILE_MOD_RULES -- blocked only on main/master; the user always
#                             sees PROTECTED_BRANCH_HINT, so `reason` may
#                             be omitted.

DESTRUCTIVE_RULES: tuple[CommandRule, ...] = (
    CommandRule(
        pattern=r"^\s*git\s+push\b.*(?:--force\b|--force-with-lease\b|\s-[a-zA-Z]*f)",
        reason="Force push rewrites remote history and can destroy others' work",
    ),
    CommandRule(
        pattern=r"^\s*git\s+push\b.*\s\+\S",
        reason="Force push via refspec (+ref) rewrites remote history",
    ),
    CommandRule(
        pattern=r"^\s*git\s+reset\b.*--hard\b",
        reason="git reset --hard destroys uncommitted changes irrecoverably",
    ),
    CommandRule(
        pattern=r"^\s*git\s+clean\b.*-[a-zA-Z]*f",
        reason="git clean -f permanently deletes untracked files",
        exclude=r"-[a-zA-Z]*n|--dry-run",
    ),
    CommandRule(
        pattern=r"^\s*git\s+checkout\s+(--\s+)?\.(\s|$)",
        reason="git checkout . discards all unstaged changes",
    ),
    CommandRule(
        pattern=r"^\s*git\s+restore\b.*\s\.(\s|$)",
        reason="git restore . discards all working tree changes",
    ),
    CommandRule(
        pattern=r"^\s*git\s+rebase\b.*--no-verify\b",
        reason="git rebase --no-verify bypasses safety hooks",
    ),
    CommandRule(
        pattern=r"^\s*git\s+branch\s+-D\s+main(\s|$)",
        reason="Force-deleting the protected branch 'main' is not allowed",
    ),
    CommandRule(
        pattern=r"^\s*git\s+branch\s+-D\s+master(\s|$)",
        reason="Force-deleting the protected branch 'master' is not allowed",
    ),
)

PROTECTED_FILE_MOD_RULES: tuple[CommandRule, ...] = (
    CommandRule(pattern=r"^\s*(rm|rmdir|mv|cp|touch|mkdir|chmod|chown|ln|install)\b"),
    CommandRule(pattern=r"\bsed\b.*\s-i"),
    CommandRule(pattern=r"\bperl\b.*\s-i"),
    CommandRule(pattern=r"\bcurl\b.*\s-[oO]\b"),
    CommandRule(pattern=r"^\s*wget\b"),
    CommandRule(pattern=r"\btee\b"),
    # Excludes /dev/null targets so noise-suppression idioms like
    # `cmd 2>/dev/null` and `cmd > /dev/null 2>&1` pass through.
    CommandRule(pattern=r"(?<![>&])\s*>(?!&)(?!\s*/dev/null\b)", match_full=True),
)


# === Helpers ===


def _run_git(*args: str, cwd: str | None = None) -> str:
    """Run git capturing stdout, failing to "" so a missing repo or binary never wedges the hook."""
    cmd = ["git"]
    if cwd:
        cmd.extend(["-C", cwd])
    cmd.extend(args)
    try:
        result = subprocess.run(  # noqa: S603
            cmd, capture_output=True, text=True, timeout=5, check=False
        )
        return result.stdout.strip()
    except subprocess.SubprocessError, FileNotFoundError:
        return ""


def _resolve_dir(path: str) -> Path | None:
    """Resolve a file or directory path to its nearest existing parent directory."""
    target = Path(path)
    dir_path = target if target.is_dir() else target.parent

    while dir_path != dir_path.parent and not dir_path.is_dir():
        dir_path = dir_path.parent

    return dir_path if dir_path.is_dir() else None


def _is_git_ignored(file_path: str) -> bool:
    """Return True when git ignores file_path, so edits to it are allowed.

    Branch protection exists to keep the protected branch's *tracked*
    history clean. A gitignored path is never committed, so modifying it
    while on main/master cannot affect that history; such edits pass
    through. `git check-ignore` prints the path when ignored and nothing
    otherwise, and works for paths that do not exist yet (e.g. a Write
    creating a new file). A file that is force-tracked yet also matches an
    ignore pattern is reported ignored here, but the commit guard still
    blocks committing it to the protected branch, so no bad history lands.
    """
    target_dir = _resolve_dir(file_path)
    if not target_dir:
        return False
    return bool(_run_git("check-ignore", str(Path(file_path).resolve()), cwd=str(target_dir)))


def _is_git_command(part: str) -> bool:
    """Return whether a command part is a git or gh invocation."""
    return bool(re.match(r"^\s*(git|gh)\b", part))


def _is_excluded(rule: CommandRule, text: str) -> bool:
    """Return whether the rule's exclude pattern matches, negating the rule (e.g. --dry-run)."""
    return bool(rule.exclude and re.search(rule.exclude, text))


def match_rules(
    command: str, rules: tuple[CommandRule, ...], *, skip_git_parts: bool = False
) -> str | None:
    """Return the first matching rule's reason, or None.

    For per-part rules, split the command on compound operators and test
    each sub-part. For full-command rules, test the entire string.

    Args:
        command: The bash command string to check.
        rules: The rule tuple to match against.
        skip_git_parts: Skip sub-command parts that start with git/gh.
    """
    for rule in rules:
        if rule.match_full:
            if re.search(rule.pattern, command) and not _is_excluded(rule, command):
                return rule.reason
        else:
            for part in bash.split_clauses(command):
                stripped = part.strip()
                if not stripped:
                    continue
                if skip_git_parts and _is_git_command(stripped):
                    continue
                if re.search(rule.pattern, stripped) and not _is_excluded(rule, stripped):
                    return rule.reason
    return None


# === Branch / git-context detection ===


def get_branch_at_path(path: str) -> str:
    """Return the git branch for the repo or worktree containing the given path."""
    dir_path = _resolve_dir(path)
    if not dir_path:
        return ""
    return _run_git("branch", "--show-current", cwd=str(dir_path))


def get_effective_branch(event: dict[str, Any]) -> str:
    """Determine the effective git branch based on tool context.

    For file tools (Edit/Write/NotebookEdit), check the branch at the
    file's location so edits inside a worktree are correctly allowed.
    Falls back to the session's cwd, then the hook process's own cwd.
    """
    tool_name: str = event.get("tool_name", "")
    tool_input: dict[str, Any] = event.get("tool_input") or {}
    cwd: str = event.get("cwd", "")

    if tool_name in ("Edit", "Write", "NotebookEdit"):
        file_path = tool_input.get("file_path", "") or tool_input.get("notebook_path", "")
        if file_path:
            return get_branch_at_path(file_path)

    if cwd:
        branch = get_branch_at_path(cwd)
        if branch:
            return branch

    return _run_git("branch", "--show-current")


def _git_dir(cwd: str) -> Path | None:
    """Return absolute git-dir for cwd, or None outside a repo."""
    raw = _run_git("rev-parse", "--git-dir", cwd=cwd)
    if not raw:
        return None
    git_path = Path(raw)
    return git_path if git_path.is_absolute() else (Path(cwd) / git_path)


def is_in_linked_worktree(cwd: str, git_dir: Path) -> bool:
    """Return whether cwd is a linked worktree (not the main repo checkout).

    Compare git-dir to git-common-dir: in a linked worktree git-dir
    points to .git/worktrees/<name> while git-common-dir points to .git/.
    """
    common_dir_raw = _run_git("rev-parse", "--git-common-dir", cwd=cwd)
    if not common_dir_raw:
        return False
    common_path = Path(common_dir_raw)
    common_dir = common_path if common_path.is_absolute() else Path(cwd) / common_path
    return git_dir.resolve() != common_dir.resolve()


def is_squash_merge_in_progress(command: str, git_dir: Path | None) -> bool:
    """Detect an in-progress squash merge.

    Two signals:
    1. SQUASH_MSG exists in the git dir (left by a prior `git merge --squash`)
    2. The command itself contains `git merge --squash` before `git commit`
    """
    if git_dir and (git_dir / "SQUASH_MSG").exists():
        return True

    squash_seen = False
    for raw_part in bash.split_clauses(command):
        stripped = raw_part.strip()
        if re.match(r"^\s*git\s+merge\s+--squash\b", stripped):
            squash_seen = True
        if re.match(r"^\s*git\s+commit\b", stripped) and squash_seen:
            return True
    return False


def creates_merge_commit(command: str) -> bool:
    """Detect a `git merge`/`git pull` that may write a merge commit.

    A merge commit modifies the protected branch directly, bypassing the
    `git commit` guard (the merge writes the commit itself, no `git commit`
    runs). Only the provably-safe forms in `SAFE_MERGE_RE` are exempt; every
    other merge/pull is treated as a potential merge commit on the branch.
    """
    for part in bash.split_clauses(command):
        stripped = part.strip()
        if MERGE_PULL_RE.match(stripped) and not SAFE_MERGE_RE.search(stripped):
            return True
    return False


# === Checks ===


def check_destructive(command: str) -> str | None:
    """Return a block reason if the command is destructive, else None."""
    return match_rules(command, DESTRUCTIVE_RULES)


def _contains_git_commit(command: str) -> bool:
    """Return whether any sub-part is a `git commit`."""
    return any(re.match(r"^\s*git\s+commit\b", p) for p in bash.split_clauses(command))


def _is_pure_git_command(command: str) -> bool:
    """Return whether every sub-part is a git/gh subcommand."""
    if not _is_git_command(command):
        return False
    return all(_is_git_command(p) or not p.strip() for p in bash.split_clauses(command))


# A redirect operator (`>`, `>>`, `2>`, `&>`, `>|`) and the path it writes to,
# captured as group 1. The path stops at whitespace or the next operator, so
# `> /tmp/log` and `2>/tmp/log` both yield `/tmp/log` while an fd dup like
# `2>&1` yields no path (the target class excludes `&`).
_REDIRECT_TARGET_RE = re.compile(r"(?:\d*|&)>>?\|?\s*([^\s|;&<>]+)")

# Commands whose non-flag arguments name files they create or modify, so those
# args are write targets for the /tmp carve-out. A command outside this set
# (e.g. `echo`, `cat`) contributes no positional write target; only its
# redirects do.
_FILE_MOD_CMDS = frozenset(
    {"rm", "rmdir", "mv", "cp", "touch", "mkdir", "chmod", "chown", "ln", "install", "tee"}
)


def _write_targets(part: str) -> list[str]:
    """Return the files a single command part creates or modifies.

    Targets come from output redirects (`> FILE`, `>> FILE`, `2> FILE`) and
    from the non-flag arguments of a leading file-mutating command (rm, mv,
    cp, touch, tee, ...). A part that writes no file (a bare `echo`, a read,
    or a write form this does not model such as `sed -i`) yields [], so the
    /tmp carve-out declines it and the normal rules decide.
    """
    targets = _REDIRECT_TARGET_RE.findall(part)
    # Drop redirect operators+targets before reading positional args so a
    # redirect path is not double-counted as a command argument.
    tokens = _REDIRECT_TARGET_RE.sub(" ", part).split()
    if tokens and tokens[0] in _FILE_MOD_CMDS:
        targets += [tok for tok in tokens[1:] if not tok.startswith("-")]
    return targets


def _targets_only_tmp(command: str) -> bool:
    """Return whether every file the command writes is under /tmp/.

    Protected-branch carve-out: a Bash command that only creates or modifies
    files in /tmp cannot affect tracked history, so it passes. Earlier this
    treated every non-flag token as a file path, which wrongly blocked
    redirect forms like `echo hi > /tmp/log` (the echoed args and the `>`
    operator are not files). Write targets now come from `_write_targets`; a
    command with no detectable write target is not a /tmp-only write.
    """
    found_target = False
    for part in bash.split_clauses(command):
        stripped = part.strip()
        if not stripped or _is_git_command(stripped):
            continue
        targets = _write_targets(stripped)
        if not targets:
            continue
        found_target = True
        if not all(t.startswith("/tmp/") for t in targets):  # noqa: S108
            return False
    return found_target


def _check_file_tool(tool_input: dict[str, Any], branch: str) -> str | None:
    """Return a block reason for an Edit/Write/NotebookEdit, or None to allow.

    Gitignored targets pass through (see `_is_git_ignored`); everything else
    on a protected branch is blocked.
    """
    file_path = tool_input.get("file_path", "") or tool_input.get("notebook_path", "")
    if file_path and _is_git_ignored(file_path):
        return None
    return f"Cannot modify files on the '{branch}' branch. {PROTECTED_BRANCH_HINT}"


def _check_protected_bash(command: str, cwd: str, branch: str) -> str | None:
    """Return a block reason for a Bash command on a protected branch, else None.

    Three ways a Bash command can modify protected history: a direct
    `git commit` (carved out for worktrees and in-progress squash merges), a
    `git merge`/`git pull` that writes a merge commit, or a non-git file
    mutation. Pure git reads and `/tmp`-only writes pass through.
    """
    if _contains_git_commit(command):
        git_dir = _git_dir(cwd) if cwd else None
        in_worktree = is_in_linked_worktree(cwd, git_dir) if git_dir else False
        is_squash = is_squash_merge_in_progress(command, git_dir)
        if not in_worktree and not is_squash:
            return f"Cannot commit directly to the '{branch}' branch. {PROTECTED_BRANCH_HINT}"

    if creates_merge_commit(command):
        return f"Cannot merge into the '{branch}' branch. {MERGE_COMMIT_HINT}"

    if _is_pure_git_command(command) or _targets_only_tmp(command):
        return None

    if match_rules(command, PROTECTED_FILE_MOD_RULES, skip_git_parts=True) is not None:
        return f"Cannot modify files on the '{branch}' branch. {PROTECTED_BRANCH_HINT}"

    return None


def check_protected_branch(event: dict[str, Any], branch: str) -> str | None:
    """Return a block reason if the action is forbidden on the protected branch."""
    tool_name: str = event.get("tool_name", "")
    tool_input: dict[str, Any] = event.get("tool_input") or {}
    cwd: str = event.get("cwd", "")

    if tool_name in ("Edit", "Write", "NotebookEdit"):
        return _check_file_tool(tool_input, branch)

    if tool_name != "Bash":
        return None

    return _check_protected_bash(tool_input.get("command", ""), cwd, branch)


def evaluate(event: dict[str, Any], cfg: Config) -> Decision | None:  # noqa: ARG001
    """Return a block/advisory Decision for branch protection, else None."""
    tool_name: str = event.get("tool_name", "")
    # Self-filter: only file-mod tools and Bash can write to a protected branch.
    # Skip others (notably Read) so the branch lookup's git call is not run per read.
    if tool_name not in ("Edit", "Write", "NotebookEdit", "Bash"):
        return None
    command: str = (event.get("tool_input") or {}).get("command", "") if tool_name == "Bash" else ""

    if tool_name == "Bash":
        reason = check_destructive(command)
        if reason:
            return Decision.blocked(
                ID, f"{reason}. Run this command outside Claude Code if you must."
            )

    branch = get_effective_branch(event)
    if branch in PROTECTED_BRANCHES:
        reason = check_protected_branch(event, branch)
        if reason:
            return Decision.blocked(ID, reason)

    if tool_name == "Bash" and GIT_C_RE.search(command):
        return Decision(block=False, context=GIT_C_ADVISORY)
    return None
