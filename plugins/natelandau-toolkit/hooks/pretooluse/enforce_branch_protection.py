"""PreToolUse hook: blocks destructive git commands and file modifications.

Blocks destructive git operations (force push, hard reset, clean -f, etc.) on
ALL branches. On protected branches (main/master) it also denies file
modifications and direct commits, and routes merge commits to the permission
prompt (an ASK) rather than a hard deny, since a merge onto trunk is sometimes
a deliberate, human-approved integration.

Every protected-branch check is keyed off the branch of the target the action
touches, not the shell's working directory: file tools (Edit/Write) use the
file's branch, file-modifying Bash commands use each write target's branch, and
git commit/merge use the repo named by `git -C <path>` / `cd <path> &&`. So a
write into a repo on main is caught wherever the shell sits, and a write into a
feature branch (or a different repo, or no repo) passes even from a main cwd.
"""

from __future__ import annotations

import os
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

# Leading per-invocation git options that precede the subcommand: `-c <key=val>`
# and `-C <path>`. Matching them lets the commit/merge detectors fire on
# `git -C <repo> commit` / `git -c k=v merge`, which a bare `git\s+commit`
# anchor would miss -- the gap that let `git -C <other-repo> commit` slip the
# guard regardless of branch.
_GIT_OPTS = r"(?:-[cC]\s+\S+\s+)*"
GIT_COMMIT_RE = re.compile(rf"^\s*git\s+{_GIT_OPTS}commit\b")
GIT_MERGE_PULL_RE = re.compile(rf"^\s*git\s+{_GIT_OPTS}(?:merge|pull)\b")
GIT_MERGE_SQUASH_RE = re.compile(rf"^\s*git\s+{_GIT_OPTS}merge\s+--squash\b")
# Pulls the `-C <path>` target out of a git clause so the op is judged against
# the repo it touches, not the shell's cwd.
_GIT_C_DIR_RE = re.compile(r"\bgit\s+(?:-c\s+\S+\s+)*-C\s+(\S+)")
# A leading `cd <dir>` clause, so the effective cwd can be tracked across
# `cd <dir> && git ...`.
_CD_RE = re.compile(r"^\s*cd\s+(\S+)")

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


# Git location vars that, if inherited from the environment, override `-C <path>`
# and hijack branch detection to the wrong repo. Git exports these when it runs a
# hook or when the shell sits inside a linked worktree, so without stripping them
# the protected-branch lookup for a path could read an unrelated repo's branch.
_GIT_LOCATION_VARS = frozenset(
    {
        "GIT_DIR",
        "GIT_COMMON_DIR",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_WORK_TREE",
    }
)


def _run_git(*args: str, cwd: str | None = None) -> str:
    """Run git capturing stdout, failing to "" so a missing repo or binary never wedges the hook."""
    cmd = ["git"]
    if cwd:
        cmd.extend(["-C", cwd])
    cmd.extend(args)
    # Strip git location vars so an ambient GIT_DIR (set under a git hook or
    # worktree) can't override `-C` and resolve the wrong repo's branch.
    env = {k: v for k, v in os.environ.items() if k not in _GIT_LOCATION_VARS}
    try:
        result = subprocess.run(  # noqa: S603
            cmd, capture_output=True, text=True, timeout=5, check=False, env=env
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
    parts = bash.split_clauses(command)  # loop-invariant; split once, not per rule
    for rule in rules:
        if rule.match_full:
            if re.search(rule.pattern, command) and not _is_excluded(rule, command):
                return rule.reason
        else:
            for part in parts:
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
        # Reuse the shared, option-tolerant matchers so a squash chain written
        # with `git -C <repo> merge --squash X && git -C <repo> commit` is still
        # recognized; a bare `git\s+commit` anchor would miss the `-C` form and
        # the commit guard would wrongly fire.
        if GIT_MERGE_SQUASH_RE.match(stripped):
            squash_seen = True
        if GIT_COMMIT_RE.match(stripped) and squash_seen:
            return True
    return False


def _strip_quotes(token: str) -> str:
    """Strip surrounding single/double quotes from a path token captured from a command.

    Command-extracted paths (`git -C '/repo'`, `rm "/repo/f"`) keep their shell
    quotes; without stripping them the path lookup would miss and the guard would
    not see the real target. Paths containing spaces are not recovered (the regex
    captures stop at the first space); those remain a known gap.
    """
    return token.strip("'\"")


def _resolve_against(path: str, cwd: str) -> str:
    """Resolve a command-extracted `path` to an absolute string against `cwd` (absolute as-is)."""
    path = _strip_quotes(path)
    if Path(path).is_absolute():
        return path
    return str(Path(cwd) / path) if cwd else path


def _git_clause_dir(clause: str, cwd: str) -> str:
    """Return the repo dir a git clause operates on, honoring `git -C <path>`.

    Falls back to the effective `cwd` when no `-C` is present, so the op is
    judged against the repo it actually touches rather than wherever git was
    invoked from.
    """
    m = _GIT_C_DIR_RE.search(clause)
    return _resolve_against(m.group(1), cwd) if m else cwd


def _cd_target(clause: str, cwd: str) -> str | None:
    """Return the dir a leading `cd <dir>` clause moves to (resolved against cwd), or None."""
    m = _CD_RE.match(clause)
    return _resolve_against(m.group(1), cwd) if m else None


# === Checks ===


def check_destructive(command: str) -> str | None:
    """Return a block reason if the command is destructive, else None."""
    return match_rules(command, DESTRUCTIVE_RULES)


# A redirect operator (`>`, `>>`, `2>`, `&>`, `>|`) and the path it writes to,
# captured as group 1. The path stops at whitespace or the next operator, so
# `> /tmp/log` and `2>/tmp/log` both yield `/tmp/log` while an fd dup like
# `2>&1` yields no path (the target class excludes `&`).
_REDIRECT_TARGET_RE = re.compile(r"(?:\d*|&)>>?\|?\s*([^\s|;&<>]+)")

# Commands whose non-flag arguments name files they create or modify, so those
# args are write targets the exempt-path carve-out can confine. A command
# outside this set (e.g. `echo`, `cat`) contributes no positional write target;
# only its redirects do. This set is deliberately the subset whose write targets
# are plain positional paths -- in-place/output writers like `sed -i`, `perl -i`,
# `curl -o`, and `wget` are NOT here because their targets can't be read off
# positionally; `_clause_write_targets` returns None for those (see below) so the
# PROTECTED_FILE_MOD_RULES still block them.
_FILE_MOD_CMDS = frozenset(
    {"rm", "rmdir", "mv", "cp", "touch", "mkdir", "chmod", "chown", "ln", "install", "tee"}
)


def _clause_write_targets(clause: str) -> list[str] | None:
    """Return the file paths a single Bash clause writes, or None if it can't be confined.

    Collects the paths the clause would create or modify: redirect targets
    (`> path`) and the positional args of a `_FILE_MOD_CMDS` write (`rm a b`,
    `touch x`). Returns None to mean "this clause performs a write whose target
    cannot be positively identified" -- a `sed -i`, `perl -i`, `curl -o`,
    `wget`, or any other shape the PROTECTED_FILE_MOD_RULES still flag. The
    caller treats None as "fall back to the effective-cwd branch", so an
    unmodeled file-mod can never slip past the guard by pointing a target at an
    exempt path. An empty list means the clause writes nothing this can see.
    """
    targets: list[str] = list(_REDIRECT_TARGET_RE.findall(clause))
    # Inspect the clause with its redirects removed: what remains must be a
    # non-file-writing command or a `_FILE_MOD_CMDS` write whose targets are its
    # positional args. Anything the block rules would still flag is a write that
    # cannot be confined, so decline the carve-out.
    remainder = _REDIRECT_TARGET_RE.sub(" ", clause).strip()
    tokens = remainder.split()
    if tokens and tokens[0] in _FILE_MOD_CMDS:
        targets.extend(t for t in tokens[1:] if not t.startswith("-"))
    elif match_rules(remainder, PROTECTED_FILE_MOD_RULES, skip_git_parts=True) is not None:
        return None
    return targets


def _target_protected_branch(target: str, cwd: str) -> str | None:
    """Return the protected branch a write to `target` would dirty, or None if harmless.

    A write is harmless when its resolved target is not inside a repo on a
    protected branch, or is gitignored. The branch is keyed off the target's own
    resolved location, not the shell's cwd: a write into a feature branch, a
    different repo, or no repo at all (a scratch path under /tmp, /dev/null, ...)
    is harmless even from a main cwd, while a write into a repo on main is caught
    wherever the shell sits -- the mirror of the Edit/Write exemption. A relative
    target with no cwd can't be located, so it is treated as harmless (the
    fail-open default; real payloads always carry a cwd).

    There is deliberately no /tmp shortcut: exempting every path under /tmp would
    also exempt a real repo that happens to live there (e.g. a worktree, or
    pytest's ephemeral repos on Linux), silently dropping protection. A /tmp
    scratch path is not in a repo, so the branch lookup already returns "" for it.
    """
    target = _strip_quotes(target)
    if Path(target).is_absolute():
        abs_target = target
    elif cwd:
        abs_target = str(Path(cwd) / target)
    else:
        return None
    # Resolve symlinks and any `..` so a link or traversal is judged by the real
    # path it lands on, the same path the gitignore check canonicalizes.
    abs_resolved = str(Path(abs_target).resolve())
    branch = get_branch_at_path(abs_resolved)
    if branch not in PROTECTED_BRANCHES:
        return None
    if _is_git_ignored(abs_resolved):
        return None
    return branch


# === Checks: target-keyed evaluators ===


def _deny_file_mod(branch: str) -> Decision:
    """Build the canonical "cannot modify files on a protected branch" deny Decision."""
    return Decision.blocked(
        ID, f"Cannot modify files on the '{branch}' branch. {PROTECTED_BRANCH_HINT}"
    )


def _evaluate_file_tool(event: dict[str, Any]) -> Decision | None:
    """Return a Decision for an Edit/Write/NotebookEdit, keyed off the target file's branch.

    A file on a protected branch is blocked unless it is gitignored (never part
    of tracked history). A file on any other branch -- or outside any repo --
    passes, so an edit inside a feature-branch worktree is allowed even when the
    main checkout sits on main.
    """
    tool_input: dict[str, Any] = event.get("tool_input") or {}
    file_path = tool_input.get("file_path", "") or tool_input.get("notebook_path", "")
    if not file_path:
        return None
    branch = get_branch_at_path(file_path)
    if branch not in PROTECTED_BRANCHES:
        return None
    if _is_git_ignored(file_path):
        return None
    return _deny_file_mod(branch)


def _git_op_decision(*, command: str, clause: str, repo_dir: str, branch: str) -> Decision | None:
    """Return a Decision for one git commit/merge clause on a protected branch, else None.

    A direct commit is denied unless carved out for a linked worktree or an
    in-progress squash merge (its follow-up `git commit` is expected). A
    merge/pull that would write a merge commit is an ASK -- routed to the
    permission prompt rather than hard-denied, since landing work on trunk is
    sometimes a deliberate, human-approved integration; the provably-safe forms
    in `SAFE_MERGE_RE` pass silently.
    """
    if GIT_COMMIT_RE.match(clause):
        git_dir = _git_dir(repo_dir) if repo_dir else None
        # git_dir is non-None only when repo_dir was truthy, so guard on git_dir alone.
        in_worktree = is_in_linked_worktree(cwd=repo_dir, git_dir=git_dir) if git_dir else False
        is_squash = is_squash_merge_in_progress(command, git_dir)
        if not in_worktree and not is_squash:
            return Decision.blocked(
                ID, f"Cannot commit directly to the '{branch}' branch. {PROTECTED_BRANCH_HINT}"
            )
        return None
    if not SAFE_MERGE_RE.search(clause):
        return Decision.ask_user(
            ID,
            f"Merging into the protected '{branch}' branch writes a merge commit "
            f"directly to it. {MERGE_COMMIT_HINT}",
        )
    return None


def _git_clause_decision(command: str, clause: str, eff_cwd: str) -> Decision | None:
    """Return a Decision for one git clause, judged against the repo it operates on, else None.

    Only commit/merge/pull can write history, so read-only git clauses
    (`status`, `log`, `diff`, ...) short-circuit before the branch lookup --
    that lookup spawns a `git` subprocess, so skipping it keeps the common case
    off the hot path.
    """
    if not (GIT_COMMIT_RE.match(clause) or GIT_MERGE_PULL_RE.match(clause)):
        return None
    repo_dir = _git_clause_dir(clause, eff_cwd)
    branch = get_branch_at_path(repo_dir) if repo_dir else _run_git("branch", "--show-current")
    if branch not in PROTECTED_BRANCHES:
        return None
    return _git_op_decision(command=command, clause=clause, repo_dir=repo_dir, branch=branch)


def _file_clause_decision(clause: str, eff_cwd: str) -> Decision | None:
    """Return a deny Decision for a file-modifying clause on a protected branch, else None.

    Each confinable write target is judged by the branch of its own resolved
    location (relative paths resolve against the effective cwd). A write whose
    target can't be read positionally falls back to the effective-cwd branch.
    """
    targets = _clause_write_targets(clause)
    if targets is None:
        branch = get_branch_at_path(eff_cwd) if eff_cwd else ""
        return _deny_file_mod(branch) if branch in PROTECTED_BRANCHES else None
    for target in targets:
        branch = _target_protected_branch(target, eff_cwd)
        if branch:
            return _deny_file_mod(branch)
    return None


def _evaluate_bash(command: str, cwd: str) -> Decision | None:
    """Return a Decision for a Bash command's protected-branch impact, else None.

    Walks the command's clauses once, left to right, tracking the effective
    working directory across `cd <dir> &&` so every git op and every file write
    is judged against the directory it actually touches. Precedence is deny >
    ask: the first denying clause (a direct commit, or a write to a tracked file)
    wins outright; a merge *ask* is held and still loses to any later deny, so a
    command that both merges and deletes a tracked file is denied rather than
    merely prompted; a lone ask, or nothing, falls through last.
    """
    eff_cwd = cwd
    pending_ask: Decision | None = None
    for raw_clause in bash.split_clauses(command):
        clause = raw_clause.strip()
        if not clause:
            continue
        if _is_git_command(clause):
            decision = _git_clause_decision(command, clause, eff_cwd)
        else:
            moved = _cd_target(clause, eff_cwd)
            if moved is not None:
                eff_cwd = moved
                continue
            decision = _file_clause_decision(clause, eff_cwd)
        if decision is None:
            continue
        if decision.block:
            return decision  # a deny outranks any pending ask; stop here
        pending_ask = pending_ask or decision
    return pending_ask


def evaluate(event: dict[str, Any], cfg: Config) -> Decision | None:  # noqa: ARG001
    """Return a deny/ask/advisory Decision for branch protection, else None."""
    tool_name: str = event.get("tool_name", "")
    # Self-filter: only file-mod tools and Bash can write to a protected branch.
    # Skip others (notably Read) so the branch lookup's git call is not run per read.
    if tool_name in ("Edit", "Write", "NotebookEdit"):
        return _evaluate_file_tool(event)
    if tool_name != "Bash":
        return None

    command: str = (event.get("tool_input") or {}).get("command", "")
    cwd: str = event.get("cwd", "")

    reason = check_destructive(command)
    if reason:
        return Decision.blocked(ID, f"{reason}. Run this command outside Claude Code if you must.")

    decision = _evaluate_bash(command, cwd)
    if decision is not None:
        return decision

    if GIT_C_RE.search(command):
        return Decision(block=False, context=GIT_C_ADVISORY)
    return None
