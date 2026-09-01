"""PreToolUse hook: put a human in the loop for a recursive rm.

A recursive delete is the one routine command that destroys work in bulk,
but the overwhelming majority of them target scratch or rebuildable output,
where a prompt is pure interruption. So the prompt is scoped by target
rather than by command: a recursive `rm` routes to the permission prompt
(`permissionDecision: "ask"`) unless *every* one of its operands is exempt.
One non-exempt operand prompts for the whole command.

Two kinds of operand are exempt:

- A *named* path inside a temp root: `/tmp/`, `/private/tmp/`, `$TMPDIR/`,
  `${TMPDIR}/`. So `rm -rf /tmp/x` is silent while `rm -rf /tmp`,
  `rm -rf /tmp/` and `rm -rf /tmp/*` all still prompt: each empties the whole
  shared temp directory, which affects every other process on the machine.
  Roots are matched as written, not resolved: on macOS `$TMPDIR` expands
  under `/var/folders/`, and protect_system hard-blocks any `/var` path, so
  the expanded spelling is blocked rather than exempt. The two `$TMPDIR`
  spellings are trusted only while the name still means the shell's temp
  directory, so a command that binds `TMPDIR` itself drops them and every
  `$TMPDIR` operand it did not resolve to a literal prompts.
- A directory a toolchain rebuilds from a manifest, matched on the operand's
  final path segment (`_ARTIFACT_DIRS`).

An operand containing `..` is never exempt, so an exempt prefix cannot be
used to walk back out to a real path (`rm -rf /tmp/../etc`).

A path the same command routed through a variable is resolved first
(`S=/tmp/work; rm -rf "$S/out"`), since the hook runs before the shell
expands anything and the bare `$S/out` would otherwise read as a project
path and prompt. Only `bash.resolve_assignments`' narrow literal cases
resolve; a value from a command substitution, one assigned behind an `&&`,
and any name the command never set all stay unresolved, and an unresolved
operand is not exempt. So the resolution can only ever remove a prompt for
a path that provably lands in a temp root, never add an exemption for one
whose target is in doubt.

Judging happens per clause, so `rm -rf /tmp/a && rm -rf /tmp/b` stays silent
while a safe leading clause cannot shield a project delete behind it.
Recursion is read per flag character (`-rf`, `-fr`, `-rvf`, `-r -f`,
`--recursive`), which a settings.json `Bash(rm -rf:*)` prefix rule cannot
express; `--force` and `--interactive` merely contain an "r" and do not
count. Operands are tokenized with shlex, so quoted paths and paths carrying
a space are read as single operands.

This hook only asks. protect_system's exit-2 blocks run first and win, so a
catastrophic target (`rm -rf ~`, `rm -rf /etc`, `rm -rf .`) stays hard blocked
and is never downgraded to a prompt, whether it is spelled literally or routed
through a variable the command sets itself (`S=~; rm -rf "$S"`), which
protect_system resolves the same way this hook does. A target neither can
resolve -- one from a command substitution or from the surrounding
environment -- reaches this hook and prompts.
"""

from __future__ import annotations

import shlex
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from lib import bash
from lib.io import Decision

if TYPE_CHECKING:
    from lib.config import Config

ID = "confirm-recursive-rm"

# Each root carries its trailing slash so only a path under it can be exempt;
# emptying the root itself affects every other process on the box.
_TEMP_ROOTS = ("/tmp/", "/private/tmp/", "$TMPDIR/", "${TMPDIR}/")  # noqa: S108

_LONG_RECURSIVE = "--recursive"

# Directories any toolchain rebuilds from a manifest or lockfile. Matched by
# name rather than location: the operand is relative to the shell's cwd, which
# a `cd` in an earlier clause can move and this hook cannot track, and a
# regenerable directory is regenerable wherever it sits. Deliberately excludes
# dist/build/target, which are build outputs in some projects and hand-written
# sources in others.
_ARTIFACT_DIRS = frozenset(
    {
        "node_modules",
        ".venv",
        ".tox",
        ".nox",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".ipynb_checkpoints",
        "htmlcov",
    }
)


def _parse_rm(tokens: list[str]) -> tuple[bool, list[str]]:
    """Split rm's arguments into a recursive flag and its operands.

    Short flags bundle and reorder freely (`-rf`, `-fr`, `-rvf`), so
    recursion is decided per character rather than per spelling. `--` ends
    option parsing, after which even a leading dash is an operand.

    A long option counts as recursive when it is any unambiguous prefix of
    `--recursive`, since getopt_long accepts abbreviations (`rm --rec -f dir`
    deletes recursively); no other rm long option starts with `r`.
    """
    recursive = False
    operands: list[str] = []
    options_ended = False
    for word in tokens:
        if options_ended or not word.startswith("-") or word == "-":
            operands.append(word)
        elif word == "--":
            options_ended = True
        elif word.startswith("--"):
            recursive = recursive or _LONG_RECURSIVE.startswith(word)
        else:
            recursive = recursive or any(char in "rR" for char in word[1:])
    return recursive, operands


def _is_exempt(operand: str, roots: tuple[str, ...]) -> bool:
    """Return True when deleting `operand` destroys nothing worth confirming."""
    path = PurePosixPath(operand)
    # An exempt prefix must not be a way to walk back out to a real path.
    if ".." in path.parts:
        return False
    for root in roots:
        if operand.startswith(root):
            # `/tmp/` and `/tmp/*` empty the shared temp root as thoroughly as
            # `/tmp` does, so only a named path *under* the root is exempt.
            remainder = operand[len(root) :].strip("/")
            return bool(remainder) and remainder != "*"
    return path.name in _ARTIFACT_DIRS


def _tokenize(clause: str) -> list[str]:
    """Split `clause` into shell words, falling back to whitespace on bad quoting.

    shlex strips the quotes, so a quoted temp path is recognized and one
    carrying a space stays a single operand.
    """
    try:
        return shlex.split(clause)
    except ValueError:
        return clause.split()


def _rm_index(tokens: list[str]) -> int | None:
    """Return the position of the rm invocation in `tokens`, else None.

    Matched on the basename so `/bin/rm` is not a way around the check.
    """
    for index, word in enumerate(tokens):
        if PurePosixPath(word).name == "rm":
            return index
    return None


def _clause_needs_confirmation(clause: str, roots: tuple[str, ...]) -> bool:
    """Return True when `clause` is a recursive rm reaching outside a temp root."""
    tokens = _tokenize(clause)
    index = _rm_index(tokens)
    if index is None:
        return False
    recursive, operands = _parse_rm(tokens[index + 1 :])
    if not recursive:
        return False
    return not (operands and all(_is_exempt(operand, roots) for operand in operands))


def evaluate(event: dict[str, Any], cfg: Config) -> Decision | None:  # noqa: ARG001
    """Return an ask Decision for a recursive rm outside a temp root, else None."""
    if event.get("tool_name") != "Bash":
        return None
    command: str = bash.join_continuations((event.get("tool_input") or {}).get("command", ""))
    if not command:
        return None
    # The `$TMPDIR` roots are exempt as a spelling, not as a resolved path, so
    # they hold only while the name still means the shell's temp directory: a
    # command that rebinds it has retargeted every reference the pass could not
    # resolve to a literal.
    roots = (
        tuple(root for root in _TEMP_ROOTS if "TMPDIR" not in root)
        if bash.binds_name(command, "TMPDIR")
        else _TEMP_ROOTS
    )
    # Judge each clause alone: a chain of temp-only deletes must stay silent,
    # and a safe leading clause must not shield a later one.
    if not any(
        _clause_needs_confirmation(clause, roots)
        for clause in bash.resolve_assignments(command, include_pipes=True)
    ):
        return None
    return Decision.ask_user(
        ID, "recursive delete of a path that is not a temp or rebuildable directory"
    )
