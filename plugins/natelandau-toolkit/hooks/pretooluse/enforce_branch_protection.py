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
A git statement is not exempt from the file-write checks: its redirects and its
other pipeline stages (`git ls-files | xargs rm`) are judged like any write.
The body of every command or process substitution (`$( )`, backticks, `<( )`)
runs, so it is judged as a command of its own, inside double quotes too
(`echo "$(rm foo.py)"` is a write).
A heredoc body is read as commands unless a known data sink consumes it
(`cat > notes.md <<'EOF'`, `python3 - <<'EOF'`, a commit message); see
`lib.bash.drop_data_heredocs`.

A write whose target cannot be read off the command (`sed -i`, `wget`) is
judged by the branch of the effective working directory instead, so it is
denied on a protected branch regardless of where it might write. An inline
interpreter program (`python3 -c`, a heredoc) is not judged at all: what it
writes is in the program text, which a launch-shape rule cannot read, and
denying every one blocks far more reads than writes.

Paths under an exempt root (`lib.exempt_paths`) skip every protected-branch
check: those trees are working stores committed to on their default branch by
design, so trunk hygiene does not apply there. The destructive rules still fire
inside them -- a force push or `reset --hard` destroys work whatever branch it
runs on.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from lib import bash, exempt_paths
from lib.io import Decision
from lib.paths import expand_user

if TYPE_CHECKING:
    from lib.config import Config
    from lib.exempt_paths import ExemptRoots

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
# Git subcommands that mutate the working tree (not history): apply a patch or
# a mailbox of patches, pop or apply a stash, remove or move tracked files,
# or restore files from the index or a commit (`git restore`, `git checkout
# -- <path>`). On a protected branch these change tracked files just like an
# edit, so they get the file-mod deny.
GIT_WORKTREE_WRITE_RE = re.compile(
    rf"^\s*git\s+{_GIT_OPTS}(?:apply\b|am\b|rm\b|mv\b|restore\b"
    r"|stash\s+(?:pop|apply)\b"
    r"|checkout\b(?=.*\s--(?:\s|$)))"
)
# Forms of those subcommands that leave the working tree alone: `git rm
# --cached` and `git restore --staged` (without `--worktree`/`-W`) change only
# the index, and `git rm -n`/`git mv -n` are dry runs.
GIT_INDEX_ONLY_RES = (
    re.compile(rf"^\s*git\s+{_GIT_OPTS}rm\b.*\s--cached\b"),
    re.compile(
        rf"^\s*git\s+{_GIT_OPTS}restore\b"
        r"(?!.*(?:--worktree\b|\s-[A-Za-z]*W))(?=.*(?:--staged\b|\s-[A-Za-z]*S))"
    ),
    re.compile(rf"^\s*git\s+{_GIT_OPTS}(?:rm|mv)\b.*\s(?:--dry-run\b|-[A-Za-z]*n\b)"),
)
# `git commit --dry-run` reports what a commit would do and writes nothing.
GIT_DRY_RUN_RE = re.compile(r"(?:^|\s)--dry-run\b")
# Flags that make a working-tree-write git clause actually read-only: `git apply`
# inspection flags (check/stat/numstat/summary) and `git am` control flags that
# do not apply a patch (abort/quit/show-current-patch). Anchored to a flag
# position (start or whitespace) so a patch FILENAME that merely contains the
# text -- `git am 0001--check.patch` -- is not mistaken for the inspect flag.
GIT_WORKTREE_READONLY_RE = re.compile(
    r"(?:^|\s)--(?:check|stat|numstat|summary|abort|quit|show-current-patch)\b"
)

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

    `pattern` is a regex tested against each pipeline stage of a command by
    default (split on `&&`, `||`, `;`, `|`), so a flag is read only from the
    stage that runs the command it belongs to. Set `match_full=True` to test
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
        # `git restore` rewrites the working tree by default, but `--staged`
        # WITHOUT `--worktree` restores only the index (an unstage) and leaves
        # the working tree intact -- non-destructive, so exempt it. The exclude
        # fires when a staged flag is present AND no worktree flag is: staged is
        # `--staged` or a short cluster ending in `S` (`-S`, `-SW`); worktree is
        # `--worktree` or a cluster containing `W` (`-W`, `-SW`), whose presence
        # means the working tree IS touched, so it must NOT be exempted.
        exclude=r"^(?!.*(?:--worktree\b|-[A-Za-z]*W))(?=.*(?:--staged\b|-[A-Za-z]*S))",
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
    # In-place edits in every spelling: bundled short flags (`sed -Ei`,
    # `perl -pi`), BSD sed's `-I`, `gsed`, and any GNU prefix of `--in-place`
    # (`--i`, `--in`). The perl cluster admits only valueless switches before
    # the `i`, so a module name in `-MList::Util` is not read as one.
    CommandRule(pattern=r"\bg?sed\b.*\s(?:-[a-zA-Z]*[iI]|--i[\w-]*)"),
    CommandRule(pattern=r"\bperl\b.*\s-[acgnlpswWtTuUX0-9]*i"),
    CommandRule(pattern=r"\bcurl\b.*\s-[oO]\b"),
    CommandRule(pattern=r"^\s*wget\b"),
    CommandRule(pattern=r"\btee\b"),
    # truncate rewrites a file's size in place; its target can't be confined
    # positionally (flags + a size arg precede the path), so block it outright.
    CommandRule(pattern=r"^\s*truncate\b"),
    # `dd of=<path>` writes the named file; /dev/null is the one harmless sink.
    CommandRule(pattern=r"\bdd\b.*\bof=", exclude=r"\bof=/dev/null\b"),
    # `find ... -delete` removes every matched path.
    CommandRule(pattern=r"\bfind\b.*\s-delete\b"),
    # `xargs rm` deletes whatever the pipeline feeds it; the leading-anchored rm
    # rule above misses it because rm is not the clause's first word. Allow
    # intervening xargs flags but require rm to be the command it runs, so
    # `xargs grep rm` (searching for the text "rm") does not trip.
    CommandRule(pattern=r"\bxargs\b\s+(?:-\S+\s+)*rm\b"),
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

    For per-part rules, split the command into pipeline stages and test each
    stage, so `sed -n p f | grep -i x` never reads grep's `-i` as sed's. For
    full-command rules, test the entire string.

    Args:
        command: The bash command string to check.
        rules: The rule tuple to match against.
        skip_git_parts: Skip stages that start with git/gh.
    """
    # Top-level stages keep a flag with its command across a piped substitution.
    # The commands inside a substitution are judged on their own by the caller.
    parts = bash.split_stages(command)
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


# === Checks ===


# A whole word that is a quoted flag or force refspec (`"-i"`, `'-f'`,
# `'+main'`). The shell strips the quotes, so the command receives it plain.
_QUOTED_FLAG_RE = re.compile(r"""(?<!\S)(["'])([-+][^\s"']*)\1(?!\S)""")


def _unquote_flags(command: str) -> str:
    """Return `command` with the quotes around a whole-word flag or refspec blanked to spaces.

    The flag rules read a quoted span as data, so `sed "-i" ...` would hide
    its in-place flag. Blanking each quote to a space keeps every byte offset,
    so a target sliced by offset from the result is the same path.
    """
    return _QUOTED_FLAG_RE.sub(lambda m: f" {m.group(2)} ", command)


def check_destructive(command: str) -> str | None:
    """Return a block reason if the command is destructive, else None."""
    return match_rules(command, DESTRUCTIVE_RULES)


# A redirect operator (`>`, `>>`, `2>`, `&>`, `>|`) and the path it writes to,
# captured as group 1. The path stops at whitespace or the next operator, so
# `> /tmp/log` and `2>/tmp/log` both yield `/tmp/log` while an fd dup like
# `2>&1` yields no path (the target class excludes `&`).
_REDIRECT_TARGET_RE = re.compile(r"(?:\d*|&)>>?\|?\s*([^\s|;&<>]+)")

# Shell syntax in a stage that is neither a command word nor an output target:
# an fd duplication or close (`2>&1`, `>&2`, `<&3`, `2>&-`), a here-string or
# heredoc operator with its word, an input redirect with its file, and an
# unquoted comment. Blanked before operands are read, so `rm x 2>&1` does not
# read `2>&1` as a path and `cp a b 2>&1` keeps `b` as its last operand.
_NON_OPERAND_RE = re.compile(
    r"\d*[<>]&\d*-?|<<<\s*\S+|\d*<<-?\s*\S+|\d*<(?![<(])\s*\S+|(?:^|(?<=\s))#.*"
)

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

# A leading `NAME=value` environment assignment that precedes a command.
_ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

# Command-launcher words whose real executable is the next non-flag word. The
# guard's command-name rules anchor on the clause head, so without skipping
# these `sudo rm`, `env rm`, `command rm`, ... would slip the rm/wget/truncate
# rules. `xargs` is deliberately absent: it has its own rule because its command
# can be preceded by its own flags.
_CMD_WRAPPERS = frozenset({"sudo", "doas", "env", "command", "builtin", "exec", "nice", "time"})

# Leading characters stripped off a command token to recover its real name: a
# backslash (alias-bypass `\rm`), a subshell/group opener glued to the command
# (`(rm`), and a directory prefix is dropped by the trailing rsplit on `/`.
_CMD_HEAD_STRIP = "\\({"


def _command_index(word_spans: list[re.Match[str]]) -> int:
    """Return the word-span index of a clause's real executable, past wrappers.

    Skips leading `NAME=value` env-assignments, subshell/group openers (`(`/`{`
    as their own token), and command launchers (`sudo`, `env`, ...) plus a
    launcher's own flags, so the executable in `( FOO=bar sudo rm )` resolves to
    the `rm` token. Returns `len(word_spans)` when no command remains (e.g. a
    bare `env`). A launcher flag that takes a separate value (`sudo -u bob`) is a
    known gap: only valueless launcher flags are skipped.
    """
    i = 0
    n = len(word_spans)
    while i < n:
        token = word_spans[i].group()
        if _ENV_ASSIGN.match(token) or token in ("(", "{"):
            i += 1
            continue
        if token.lstrip("\\").rsplit("/", 1)[-1] in _CMD_WRAPPERS:
            i += 1
            while i < n and word_spans[i].group().startswith("-"):
                i += 1
            continue
        return i
    return n


# A chmod MODE operand: octal (`755`) or a comma-joined symbolic list
# (`+x`, `u+x,go-w`, `a=r`). A mode written with a leading `-` (`-x`) is
# already dropped with the flags.
_CHMOD_MODE_RE = re.compile(
    r"^(?:[0-7]{1,4}|[ugoa]*(?:[-+=](?:[rwxXst]*|[ugo]))+)(?:,[ugoa]*(?:[-+=](?:[rwxXst]*|[ugo]))+)*$"
)


# `--reference` or any GNU-accepted prefix of it; `--ref` is the shortest
# that no other chmod/chown option shares.
_REFERENCE_RE = re.compile(r"(?:^|\s)--ref")


def _drop_mode_operand(head: str, operands: list[str], clause: str) -> list[str]:
    """Drop the leading chmod MODE or chown OWNER operand, which names no file.

    Read as a path, `+x` or `nate:staff` resolves into the cwd's repo, so a
    chmod aimed at a file in another repo is judged by the shell's branch.
    With `--reference` (or a GNU prefix of it, `--ref`), every operand is a
    file, so none is dropped. A chmod
    operand is dropped only when it is shaped like a mode, so a mode spelled
    `-x` (skipped as a flag) cannot shift a real file into the mode slot.
    """
    if not operands or head not in ("chmod", "chown") or _REFERENCE_RE.search(clause):
        return operands
    if head == "chmod" and not _CHMOD_MODE_RE.match(bash.strip_quotes(operands[0])):
        return operands
    return operands[1:]


def _clause_write_targets(clause: str) -> list[str] | None:
    """Return the file paths a Bash statement writes, or None if it can't be confined.

    Collect the targets of each pipeline stage on its own, so a writer in a
    later stage (`echo y | rm /repo/foo.py`) is judged by its own operands,
    not by the shell's directory. One unconfinable stage makes the whole
    statement unconfinable.
    """
    targets: list[str] = []
    for stage in bash.split_stages(clause):
        stage_targets = _stage_write_targets(stage.strip())
        if stage_targets is None:
            return None
        targets.extend(stage_targets)
    return targets


# Short options of cp/ln/install that take a value (attached or as the next
# word), and the valueless short options of the GNU and BSD versions. A short
# option outside both sets makes the command unparsable. BSD install's `-S` is
# valueless, so reading it as GNU's `-S SUFFIX` can only swallow an operand and
# fall back to judging every operand.
_COPY_VALUE_SHORT = {"cp": "St", "ln": "St", "install": "Smogt"}
_COPY_FLAG_SHORT = {"cp": "abcdfHilLnNPpRrsTuvxXZ", "ln": "bdFfhiLnPrsTvw", "install": "bcCdDpsvZ"}
# Long options of cp/ln/install, each mapped to whether it requires a value.
# An option whose value is optional (`--backup[=CONTROL]`) takes it only after
# `=`, so it maps to False. GNU also accepts a required value as the next word
# and any unambiguous prefix of a name (`--target`); a name that matches none
# of these, or more than one, makes the command unparsable.
_COPY_LONG: dict[str, dict[str, bool]] = {
    "cp": {
        **dict.fromkeys(
            (
                "--archive",
                "--attributes-only",
                "--backup",
                "--copy-contents",
                "--debug",
                "--dereference",
                "--force",
                "--interactive",
                "--link",
                "--no-dereference",
                "--no-clobber",
                "--no-target-directory",
                "--one-file-system",
                "--parents",
                "--preserve",
                "--recursive",
                "--reflink",
                "--remove-destination",
                "--strip-trailing-slashes",
                "--symbolic-link",
                "--update",
                "--verbose",
                "--keep-directory-symlink",
                "--context",
            ),
            False,
        ),
        **dict.fromkeys(("--target-directory", "--suffix", "--sparse", "--no-preserve"), True),
    },
    "ln": {
        **dict.fromkeys(
            (
                "--backup",
                "--directory",
                "--force",
                "--interactive",
                "--logical",
                "--no-dereference",
                "--no-target-directory",
                "--physical",
                "--relative",
                "--symbolic",
                "--verbose",
            ),
            False,
        ),
        **dict.fromkeys(("--target-directory", "--suffix"), True),
    },
    "install": {
        **dict.fromkeys(
            (
                "--backup",
                "--compare",
                "--debug",
                "--directory",
                "--preserve-timestamps",
                "--strip",
                "--no-target-directory",
                "--verbose",
                "--preserve-context",
                "--context",
            ),
            False,
        ),
        **dict.fromkeys(
            (
                "--target-directory",
                "--suffix",
                "--mode",
                "--owner",
                "--group",
                "--strip-program",
            ),
            True,
        ),
    },
}
# A destination holding one of these is expanded by the shell (`$D`, `$(..)`,
# a backtick, a glob, a brace list), so the hook cannot read the real path.
_UNREADABLE_PATH_CHARS = frozenset("$`*?[{")


@dataclass(slots=True)
class _CopyArgs:
    """The parsed arguments of a cp/ln/install command.

    The sources of a copy or link are only read, so judging them as writes
    blocks a copy out of a protected repo. `destinations` names what the
    command writes, or None when its options cannot be parsed.
    """

    head: str
    operands: list[str] = field(default_factory=list)
    target_dir: str | None = None
    creates_dirs: bool = False

    def parse(self, words: list[str]) -> bool:
        """Read `words` (the arguments after the command name); return False if unparsable."""
        options_done = False
        i = 0
        while i < len(words):
            word = words[i]
            nxt = words[i + 1] if i + 1 < len(words) else None
            i += 1
            if options_done or not word.startswith("-") or word == "-":
                self.operands.append(word)
                continue
            if word == "--":
                options_done = True
                continue
            used = self._long(word, nxt) if word.startswith("--") else self._short(word, nxt)
            if used is None:
                return False
            i += used
        return True

    def _long(self, word: str, nxt: str | None) -> int | None:
        """Apply one long option; return how many following words it used, or None."""
        name, eq, value = word.partition("=")
        options = _COPY_LONG[self.head]
        matches = [name] if name in options else [opt for opt in options if opt.startswith(name)]
        if len(matches) != 1:
            return None
        option = matches[0]
        if option == "--directory" and self.head == "install":
            self.creates_dirs = True
        if not options[option]:
            return 0
        used = 0
        if not eq:
            if nxt is None:
                return None
            value, used = nxt, 1
        if option == "--target-directory":
            self.target_dir = value
        return used

    def _short(self, word: str, nxt: str | None) -> int | None:
        """Apply one short-option cluster; return how many following words it used, or None."""
        cluster = word[1:]
        for j, flag in enumerate(cluster):
            if flag in _COPY_VALUE_SHORT[self.head]:
                value, used = cluster[j + 1 :], 0
                if not value:
                    if nxt is None:
                        return None
                    value, used = nxt, 1
                if flag == "t":
                    self.target_dir = value
                return used
            if flag not in _COPY_FLAG_SHORT[self.head]:
                return None
            if self.head == "install" and flag == "d":
                self.creates_dirs = True
        return 0

    @property
    def destinations(self) -> list[str] | None:
        """Return the written paths, or None when they cannot be told apart from sources.

        That is every operand for `install -d`, else the target directory, else
        the last operand, else a lone `ln` operand's basename in the cwd.
        """
        if self.creates_dirs:
            return self.operands
        if self.target_dir is not None:
            chosen = [self.target_dir]
        elif len(self.operands) > 1:
            chosen = [self.operands[-1]]
        elif self.head == "ln" and self.operands:
            chosen = [Path(bash.strip_quotes(self.operands[0])).name]
        else:
            return None
        if any(_UNREADABLE_PATH_CHARS & set(path) for path in chosen):
            return None
        return chosen


def _copy_destinations(head: str, words: list[str]) -> list[str] | None:
    """Return the paths a cp/ln/install writes, or None to judge every operand instead."""
    args = _CopyArgs(head)
    return args.destinations if args.parse(words) else None


def _operand_paths(operand: str) -> list[str]:
    """Return the paths an operand may name: itself, plus the paths its substitutions mention.

    The hook cannot run `$(echo /repo/foo.py)` to learn the path it prints, so
    every path-like word in a substitution body is judged as well. Over-matching
    costs a false block, never a missed write.
    """
    paths = [operand]
    for body in bash.substitution_bodies(operand):
        paths.extend(
            word.strip("\"'()`")
            for word in body.split()
            if "/" in word and not word.startswith("-")
        )
    return paths


def _stage_write_targets(clause: str) -> list[str] | None:
    """Return the file paths a single pipeline stage writes, or None if it can't be confined.

    Collects the paths the clause would create or modify: redirect targets
    (`> path`) and the positional args of a `_FILE_MOD_CMDS` write (`rm a b`,
    `touch x`). Returns None to mean "this clause performs a write whose target
    cannot be positively identified" -- a `sed -i`, `perl -i`, `curl -o`,
    `wget`, or any other shape the PROTECTED_FILE_MOD_RULES still flag. The
    caller treats None as "fall back to the effective-cwd branch", so an
    unmodeled file-mod can never slip past the guard by pointing a target at an
    exempt path. An empty list means the clause writes nothing this can see.
    """
    # Scan a quote-masked view of the clause so a quoted metacharacter (the `>`
    # in `awk 'c>=2'` or `grep 'a>b'`) is never read as a redirect; mask_quoted
    # preserves byte offsets, so each target is sliced back out of the original.
    # mask_comparisons additionally blanks a `>` that is an arithmetic/test
    # comparison (`(( a > b ))`, `[[ 5 > 3 ]]`). Substitutions are blanked
    # first: their bodies (`$(cat x > f)`) run as commands of their own and are
    # judged separately, so their text is not this stage's operands.
    masked = bash.mask_comparisons(bash.mask_quoted(bash.blank_substitutions(clause)))
    targets: list[str] = [
        clause[m.start(1) : m.end(1)] for m in _REDIRECT_TARGET_RE.finditer(masked)
    ]
    # Inspect the clause with its redirects removed: what remains must be a
    # non-file-writing command or a `_FILE_MOD_CMDS` write whose targets are its
    # positional args. Anything the block rules would still flag is a write that
    # cannot be confined, so decline the carve-out. Redirect spans are blanked
    # with equal-length filler so the remainder stays offset-aligned with the
    # original, letting positional targets be sliced from `clause` by span.
    remainder = _REDIRECT_TARGET_RE.sub(lambda m: " " * len(m.group()), masked)
    remainder = _NON_OPERAND_RE.sub(lambda m: " " * len(m.group()), remainder)
    word_spans = list(re.finditer(r"\S+", remainder))
    # Resolve the real executable past any wrapper/env/subshell prefix and strip
    # its path, so `sudo rm`, `/bin/rm`, `env rm`, and `( rm` all read as `rm`.
    cmd_index = _command_index(word_spans)
    has_command = cmd_index < len(word_spans)
    head = ""
    if has_command:
        head = word_spans[cmd_index].group().lstrip(_CMD_HEAD_STRIP).rsplit("/", 1)[-1]
    if head in _FILE_MOD_CMDS:
        # Positional args are write targets, minus flags and bare shell grouping
        # punctuation (`)`/`}`/`;` from a subshell or brace group, which are not
        # paths -- so `( rm /tmp/x )` confines to /tmp instead of also "writing" `)`.
        operands = [
            clause[m.start() : m.end()]
            for m in word_spans[cmd_index + 1 :]
            if not m.group().startswith("-") and m.group().strip("(){};&") != ""
        ]
        if head in _COPY_VALUE_SHORT:
            words = [
                clause[m.start() : m.end()]
                for m in word_spans[cmd_index + 1 :]
                if m.group().strip("(){};&") != ""
            ]
            destinations = _copy_destinations(head, words)
            if destinations is not None:
                targets.extend(destinations)
                return targets
        targets.extend(
            path
            for operand in _drop_mode_operand(head, operands, clause)
            for path in _operand_paths(operand)
        )
        return targets
    # Match the block rules on the full remainder (catches a non-anchored writer
    # anywhere, e.g. `sed -i` even inside `x=$(sed -i ...)`), then, only when the
    # head was actually rewritten by a wrapper/path prefix, on the de-wrapped
    # command so an anchored rule like `^\s*wget`/`^\s*truncate` still fires.
    # Targets above come from the original spans, so basenaming cannot move a path.
    remainder_stripped = remainder.strip()
    blocked = match_rules(remainder_stripped, PROTECTED_FILE_MOD_RULES, skip_git_parts=True)
    if blocked is None and has_command:
        dewrapped = (head + remainder[word_spans[cmd_index].end() :]).strip()
        if dewrapped != remainder_stripped:
            blocked = match_rules(dewrapped, PROTECTED_FILE_MOD_RULES, skip_git_parts=True)
    if blocked is not None:
        return None
    return targets


def _target_protected_branch(target: str, cwd: str, exempt: ExemptRoots) -> str | None:
    """Return the protected branch a write to `target` would dirty, or None if harmless.

    A write is harmless when its resolved target is not inside a repo on a
    protected branch, or is gitignored. The branch is keyed off the target's own
    resolved location, not the shell's cwd: a write into a feature branch, a
    different repo, or no repo at all (a scratch path under /tmp, /dev/null, ...)
    is harmless even from a main cwd, while a write into a repo on main is caught
    wherever the shell sits -- the mirror of the Edit/Write exemption. A relative
    target with no cwd can't be located, so it is treated as harmless (the
    fail-open default; real payloads always carry a cwd). A leading `~` is
    expanded first, since the hook sees the command before the shell does and a
    tilde joined onto the cwd names nothing.

    There is deliberately no /tmp shortcut: exempting every path under /tmp would
    also exempt a real repo that happens to live there (e.g. a worktree, or
    pytest's ephemeral repos on Linux), silently dropping protection. A /tmp
    scratch path is not in a repo, so the branch lookup already returns "" for it.
    """
    expanded = expand_user(bash.strip_quotes(target))
    if expanded.is_absolute():
        abs_target = str(expanded)
    elif cwd:
        abs_target = str(Path(cwd) / expanded)
    else:
        return None
    # Resolve symlinks and any `..` so a link or traversal is judged by the real
    # path it lands on, the same path the gitignore check canonicalizes.
    abs_resolved = str(Path(abs_target).resolve())
    if exempt.contains(abs_resolved):
        return None
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


def _evaluate_file_tool(event: dict[str, Any], exempt: ExemptRoots) -> Decision | None:
    """Return a Decision for an Edit/Write/NotebookEdit, keyed off the target file's branch.

    A file on a protected branch is blocked unless it is gitignored (never part
    of tracked history) or under an exempt root. A file on any other branch --
    or outside any repo -- passes, so an edit inside a feature-branch worktree
    is allowed even when the main checkout sits on main.
    """
    tool_input: dict[str, Any] = event.get("tool_input") or {}
    file_path = tool_input.get("file_path", "") or tool_input.get("notebook_path", "")
    if not file_path:
        return None
    if exempt.contains(file_path, event.get("cwd", "")):
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


def _git_clause_decision(
    command: str, clause: str, eff_cwd: str, exempt: ExemptRoots
) -> Decision | None:
    """Return a Decision for one git clause, judged against the repo it operates on, else None.

    Only commit/merge/pull (history) and apply/am/stash-pop (working tree) can
    write, so every other git clause (`status`, `log`, `diff`, ...) short-circuits
    before the branch lookup -- that lookup spawns a `git` subprocess, so skipping
    it keeps the common read-only case off the hot path.
    """
    is_commit = GIT_COMMIT_RE.match(clause) is not None and not GIT_DRY_RUN_RE.search(clause)
    is_history = bool(is_commit or GIT_MERGE_PULL_RE.match(clause))
    is_worktree_write = (
        GIT_WORKTREE_WRITE_RE.match(clause) is not None
        and GIT_WORKTREE_READONLY_RE.search(clause) is None
        and not any(regex.match(clause) for regex in GIT_INDEX_ONLY_RES)
    )
    if not (is_history or is_worktree_write):
        return None
    repo_dir = bash.git_clause_dir(clause, eff_cwd)
    if exempt.contains(repo_dir):
        return None
    branch = get_branch_at_path(repo_dir) if repo_dir else _run_git("branch", "--show-current")
    if branch not in PROTECTED_BRANCHES:
        return None
    # A working-tree write (apply/am/stash pop) dirties tracked files exactly as
    # an edit would, so it gets the file-mod deny. History writes keep their own
    # commit/merge handling (direct-commit deny, merge ASK).
    if is_worktree_write and not is_history:
        return _deny_file_mod(branch)
    return _git_op_decision(command=command, clause=clause, repo_dir=repo_dir, branch=branch)


def _file_clause_decision(clause: str, eff_cwd: str, exempt: ExemptRoots) -> Decision | None:
    """Return a deny Decision for a file-modifying clause on a protected branch, else None.

    Each confinable write target is judged by the branch of its own resolved
    location (relative paths resolve against the effective cwd). A write whose
    target can't be read positionally falls back to the effective-cwd branch.
    """
    targets = _clause_write_targets(clause)
    if targets is None:
        if exempt.contains(eff_cwd):
            return None
        branch = get_branch_at_path(eff_cwd) if eff_cwd else ""
        return _deny_file_mod(branch) if branch in PROTECTED_BRANCHES else None
    for target in targets:
        branch = _target_protected_branch(target, eff_cwd, exempt)
        if branch:
            return _deny_file_mod(branch)
    return None


# Commands that take a substitution's output as data, so a heredoc inside the
# substitution (`git commit -m "$(cat <<'EOF' ... EOF)"`) is a message, not
# code. Under any other command (`eval`, `sh -c`, `sudo`, or a substitution in
# command position) the output can run, so the heredoc body is judged.
_DATA_ARG_COMMANDS = frozenset(
    {"git", "gh", "echo", "printf", "cat", "tee", "test", "[", "[[", "export", "local", "declare"}
)
# How deep substitutions inside substitutions are judged; deeper ones pass.
_MAX_SUBSTITUTION_DEPTH = 8


def _output_is_data(clause: str) -> bool:
    """Return whether a statement uses its substitutions' output only as data."""
    blanked = bash.mask_quoted(bash.blank_substitutions(clause))
    spans = list(re.finditer(r"\S+", blanked))
    i = 0
    while i < len(spans) and _ENV_ASSIGN.match(spans[i].group()):
        i += 1
    if i == len(spans):
        return True  # a bare assignment (`MSG=$(cat <<EOF ...)`) stores the output
    head = clause[spans[i].start() : spans[i].end()]
    return head.rsplit("/", 1)[-1] in _DATA_ARG_COMMANDS


def _judge_bash(
    command: str, cwd: str, exempt: ExemptRoots, *, output_is_data: bool = True, depth: int = 0
) -> Decision | None:
    """Return a Decision for a Bash command or a substitution body, else None.

    Drops data heredoc bodies (unless the output can run as code) and
    unquotes flags, then applies the destructive rules and the
    protected-branch checks.
    """
    if output_is_data:
        command = bash.drop_data_heredocs(command)
    command = _unquote_flags(command)
    reason = check_destructive(command)
    if reason:
        return Decision.blocked(ID, f"{reason}. Run this command outside Claude Code if you must.")
    return _evaluate_bash(command, cwd, exempt, depth=depth)


def _evaluate_bash(
    command: str, cwd: str, exempt: ExemptRoots, *, depth: int = 0
) -> Decision | None:
    """Return a Decision for a Bash command's protected-branch impact, else None.

    Walks the command's statements once, left to right, tracking the effective
    working directory across `cd <dir> &&` (but not across a backgrounded
    `cd <dir> &` or a `cd` in a pipeline, which run in a subshell), so every
    git op and every file write is judged against the directory it touches. Within a statement,
    every git stage (including one in a later pipeline stage or inside a
    substitution) gets the git checks, and the whole statement also gets the
    file-write checks, so `git show x > foo.py` and `git ls-files | xargs rm`
    are judged as the writes they are. The body of each command or process
    substitution in the statement runs, so it is judged as a command of its
    own (`echo $(rm foo.py)`). Precedence is deny > ask: the first deny (a
    direct commit, or a write to a tracked file) wins outright; a merge *ask*
    is held and still loses to any later deny, so a command that both merges
    and deletes a tracked file is denied rather than merely prompted; a lone
    ask, or nothing, falls through last.
    """
    eff_cwd = cwd
    pending_ask: Decision | None = None
    for raw_clause, operator_after in bash.split_statements(command):
        clause = raw_clause.strip()
        if not clause:
            continue
        decisions: list[Decision | None] = []
        if depth < _MAX_SUBSTITUTION_DEPTH:
            output_is_data = _output_is_data(clause)
            decisions.extend(
                _judge_bash(body, eff_cwd, exempt, output_is_data=output_is_data, depth=depth + 1)
                for body in bash.substitution_bodies(clause)
            )
        moved = bash.cd_target(clause, eff_cwd)
        # A backgrounded `cd`, or one in a pipeline, runs in a subshell, so it
        # moves nothing for the statements after it.
        if moved is not None and operator_after != "&" and len(bash.split_stages(clause)) == 1:
            eff_cwd = moved
        else:
            decisions.extend(
                _git_clause_decision(command, stage.strip(), eff_cwd, exempt)
                for stage in bash.split_stages(clause)
                if _is_git_command(stage.strip())
            )
            decisions.append(_file_clause_decision(clause, eff_cwd, exempt))
        for decision in decisions:
            if decision is None:
                continue
            if decision.block:
                return decision  # a deny outranks any pending ask; stop here
            pending_ask = pending_ask or decision
    return pending_ask


def evaluate(event: dict[str, Any], cfg: Config) -> Decision | None:
    """Return a deny/ask/advisory Decision for branch protection, else None."""
    tool_name: str = event.get("tool_name", "")
    # Self-filter: only file-mod tools and Bash can write to a protected branch.
    # Skip others (notably Read) so the branch lookup's git call is not run per read.
    if tool_name not in ("Edit", "Write", "NotebookEdit", "Bash"):
        return None
    exempt = exempt_paths.resolve(cfg.exempt_paths)
    if tool_name != "Bash":
        return _evaluate_file_tool(event, exempt)

    command: str = bash.join_continuations((event.get("tool_input") or {}).get("command", ""))
    cwd: str = event.get("cwd", "")

    decision = _judge_bash(command, cwd, exempt)
    if decision is not None:
        return decision

    if GIT_C_RE.search(command):
        return Decision(block=False, context=GIT_C_ADVISORY)
    return None
