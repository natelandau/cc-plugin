"""Unit tests for hooks/lib/bash.py: quote-aware command splitting and masking.

The split helpers feed every Bash-matching PreToolUse hook, so the contract
under test is twofold: a real sequence/pipeline operator splits a command, but
the identical character inside single or double quotes (an `awk` program, an
`echo` literal) is data and must not split or be read as syntax. `mask_quoted`
is the primitive both behaviors rest on, so it is exercised directly too.
"""

from __future__ import annotations

import importlib
import sys
import time
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path
    from types import ModuleType


@pytest.fixture
def bash(hooks_dir: Path) -> ModuleType:
    """Import lib.bash with the hooks dir on sys.path."""
    sys.path.insert(0, str(hooks_dir))
    try:
        return importlib.import_module("lib.bash")
    finally:
        sys.path.pop(0)


# === split_clauses: default (sequence) operators ===

_SEQUENCE_CASES: tuple[tuple[str, list[str]], ...] = (
    # Real operators split, with the surrounding whitespace trimmed at the seam.
    ("a && b", ["a", "b"]),
    ("a || b", ["a", "b"]),
    ("a ; b", ["a", "b"]),
    ("git add . && git commit -m x", ["git add .", "git commit -m x"]),
    ("a && b || c ; d", ["a", "b", "c", "d"]),
    # No operator: the whole command is one clause.
    ("echo hello", ["echo hello"]),
    # Operators inside single quotes are data -- one clause, verbatim.
    ("echo 'a && b'", ["echo 'a && b'"]),
    ("echo 'a; b; c'", ["echo 'a; b; c'"]),
    ("awk '/x/ || /y/ {print}' file", ["awk '/x/ || /y/ {print}' file"]),
    ("awk 'c>=2 && c<5' file", ["awk 'c>=2 && c<5' file"]),
    # Operators inside double quotes are data too.
    ('echo "a && b"', ['echo "a && b"']),
    ('python -c "print(1 if a else 2); x()"', ['python -c "print(1 if a else 2); x()"']),
    # A quoted operator next to a real one: split only at the real (unquoted) one.
    ("echo 'a && b' && rm foo", ["echo 'a && b'", "rm foo"]),
    ("echo 'safe ; here' ; rm foo", ["echo 'safe ; here'", "rm foo"]),
    # A backslash-escaped operator is literal, so it does not split.
    (r"echo a\&\& b", [r"echo a\&\& b"]),
)


@pytest.mark.parametrize(("command", "expected"), _SEQUENCE_CASES)
def test_split_clauses_sequence(bash: ModuleType, command: str, expected: list[str]) -> None:
    """Verify default splitting fires on real sequence operators but not quoted ones."""
    assert bash.split_clauses(command) == expected


# === split_clauses: include_pipes ===

_PIPELINE_CASES: tuple[tuple[str, list[str]], ...] = (
    # A real pipe is its own stage (whitespace kept; callers strip).
    ("a | b", ["a ", " b"]),
    ("cat f | grep x | wc -l", ["cat f ", " grep x ", " wc -l"]),
    # A pipe inside quotes is data -- one stage.
    ("grep '|' file", ["grep '|' file"]),
    ("awk -F '|' '{print $2}' file", ["awk -F '|' '{print $2}' file"]),
    # Background `&` splits, but a quoted `&` does not.
    ("server & tail log", ["server ", " tail log"]),
    ("echo 'a & b'", ["echo 'a & b'"]),
)


@pytest.mark.parametrize(("command", "expected"), _PIPELINE_CASES)
def test_split_clauses_pipes(bash: ModuleType, command: str, expected: list[str]) -> None:
    """Verify include_pipes splitting fires on real pipes/background but not quoted ones."""
    assert bash.split_clauses(command, include_pipes=True) == expected


# === mask_quoted ===


@pytest.mark.parametrize(
    "command",
    [
        "echo 'a && b'",
        'echo "a; b"',
        "awk 'c>=2 && x' file",
        r"echo a\;b",
        "plain command with no quotes",
        "",
    ],
)
def test_mask_quoted_preserves_length(bash: ModuleType, command: str) -> None:
    """Verify masking is length- and offset-preserving so sliced spans map back."""
    assert len(bash.mask_quoted(command)) == len(command)


def test_mask_quoted_neutralizes_quoted_metacharacters(bash: ModuleType) -> None:
    """Verify metacharacters inside quotes vanish from the masked view while bare ones stay."""
    # Quoted operators/redirects are gone from the masked string...
    masked = bash.mask_quoted("awk 'c>=2 && a;b' file > out.txt")
    quoted_region = masked[masked.index("awk") + 4 : masked.index(" file")]
    assert ">" not in quoted_region
    assert "&" not in quoted_region
    assert ";" not in quoted_region
    # ...but the real trailing redirect operator and its target survive unmasked.
    assert "> out.txt" in masked


def test_mask_quoted_leaves_unquoted_text_unchanged(bash: ModuleType) -> None:
    """Verify characters outside quotes are returned byte-for-byte."""
    cmd = "rm foo.py && git status"
    assert bash.mask_quoted(cmd) == cmd


# === mask_comparisons ===

# Commands whose `>` is a comparison operator, not a redirect: after masking it
# must be gone so a redirect scan never fires on it.
_COMPARISON_CASES: tuple[str, ...] = (
    "(( a > b ))",
    "$(( a > b ))",
    "[[ 5 > 3 ]]",
    "if (( i > 0 )); then echo y; fi",
    "x=$((a>b))",
    "[[ $x > $y ]] && echo big",
    "(( (a > b) > c ))",  # nested arithmetic grouping
    "if [[ x > y ]]; then echo hi; fi",  # [[ at command position after a keyword
)

# Commands whose `>` is a real redirect and must survive masking -- notably a
# redirect inside a command substitution, which runs and writes a file.
_REAL_REDIRECT_CASES: tuple[str, ...] = (
    "echo hi > file",
    "$(cat a > b)",
    "result=$(cat a > b)",
    "(( a > b )) && cat x > f",  # arith `>` masked, real `> f` survives
    "[[ -n $(cmd > f) ]]",  # cmd-sub redirect inside a test still scans
    "echo `cat a > b`",  # backtick command substitution
    "echo [[ > file",  # `[[` as a plain argument is not a test, so `>` redirects
)


@pytest.mark.parametrize("command", _COMPARISON_CASES)
def test_mask_comparisons_blanks_arith_test_operators(bash: ModuleType, command: str) -> None:
    """Verify a `>` comparing values in (( ))/$(( ))/[[ ]] is masked out."""
    assert ">" not in bash.mask_comparisons(bash.mask_quoted(command))


@pytest.mark.parametrize("command", _REAL_REDIRECT_CASES)
def test_mask_comparisons_keeps_real_redirects(bash: ModuleType, command: str) -> None:
    """Verify a real redirect `>` (including inside a command substitution) survives."""
    assert ">" in bash.mask_comparisons(bash.mask_quoted(command))


# === path resolution: resolve_against / cd_target / git_clause_dir ===


def test_resolve_against_expands_a_leading_tilde(
    bash: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Verify `~` names the home directory rather than a child of the cwd.

    The hook reads the command before the shell expands anything, so joining
    the tilde onto the cwd would point every branch lookup at a path that does
    not exist and quietly allow the action.
    """
    # Given a home directory and a command-extracted path written with a tilde
    monkeypatch.setenv("HOME", str(tmp_path))

    # When resolving it against an unrelated cwd
    resolved = bash.resolve_against("~/repo/file.py", "/somewhere/else")

    # Then it lands in the home directory
    assert resolved == str(tmp_path / "repo" / "file.py")


def test_resolve_against_keeps_an_unexpandable_tilde(bash: ModuleType) -> None:
    """Verify a `~user` that names no account stays a literal relative path."""
    # Given a tilde path for an account that does not exist
    # When resolving it against a cwd
    resolved = bash.resolve_against("~nosuchuser42/store", "/work")

    # Then it is anchored to the cwd rather than raising
    assert resolved == "/work/~nosuchuser42/store"


def test_cd_target_expands_a_leading_tilde(
    bash: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Verify `cd ~/repo` tracks to the home directory."""
    # Given a home directory
    monkeypatch.setenv("HOME", str(tmp_path))

    # When reading the target of a tilde `cd`
    # Then the effective cwd is the expanded path
    assert bash.cd_target("cd ~/repo", "/somewhere/else") == str(tmp_path / "repo")


def test_git_clause_dir_expands_a_leading_tilde(
    bash: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Verify `git -C ~/repo` names the repo in the home directory."""
    # Given a home directory
    monkeypatch.setenv("HOME", str(tmp_path))

    # When reading the repo a tilde `-C` clause operates on
    # Then it is the expanded path, not one built from the cwd
    assert bash.git_clause_dir("git -C ~/repo commit", "/somewhere/else") == str(tmp_path / "repo")


# === resolve_assignments: replaying a command's own literal assignments ===

_RESOLVED_CASES: tuple[tuple[str, list[str]], ...] = (
    # The reported shape: a scratch dir bound to a variable, then deleted.
    (
        'S=/private/tmp/scratch; rm -rf "$S/a" "$S/b"',
        ["S=/private/tmp/scratch", 'rm -rf "/private/tmp/scratch/a" "/private/tmp/scratch/b"'],
    ),
    # Braced, bare, and `export`-prefixed spellings all resolve.
    ("S=/tmp/w; rm -rf ${S}/out", ["S=/tmp/w", "rm -rf /tmp/w/out"]),
    ("export S=/tmp/w; rm -rf $S", ["export S=/tmp/w", "rm -rf /tmp/w"]),
    # A newline separates statements just as `;` does.
    ("S=/tmp/w\nrm -rf $S/out", ["S=/tmp/w", "rm -rf /tmp/w/out"]),
    # A value may itself reference an earlier name.
    ("A=/tmp/w; B=$A/sub; rm -rf $B/out", ["A=/tmp/w", "B=/tmp/w/sub", "rm -rf /tmp/w/sub/out"]),
    # A quoted value keeps its space and stays one word.
    ('S="/tmp/a b"; rm -rf "$S/out"', ['S="/tmp/a b"', 'rm -rf "/tmp/a b/out"']),
    # The last unconditional assignment wins.
    ("S=/tmp/a; S=/tmp/b; rm -rf $S", ["S=/tmp/a", "S=/tmp/b", "rm -rf /tmp/b"]),
    # An empty assignment is a real value: `$S/out` is `/out`, not a temp path.
    ("S=; rm -rf $S/out", ["S=", "rm -rf /out"]),
    # An unrelated environment prefix forgets only the name it sets.
    (
        "S=/tmp/w; FOO=1 make; rm -rf $S/out",
        ["S=/tmp/w", "FOO=1 make", "rm -rf /tmp/w/out"],
    ),
)


@pytest.mark.parametrize(("command", "expected"), _RESOLVED_CASES)
def test_resolve_assignments_replays_literal_assignments(
    command: str, expected: list[str], bash: ModuleType
) -> None:
    """Verify a variable a command sets literally is resolved in its later clauses."""
    # Given a command that binds a path to a variable before using it
    # When splitting it with assignment resolution
    # Then the later clauses name the path the shell would actually touch
    assert bash.resolve_assignments(command) == expected


_UNRESOLVED_CASES: tuple[tuple[str, str], ...] = (
    # A value this pass cannot evaluate records nothing.
    ("S=$(mktemp -d); rm -rf $S/out", "rm -rf $S/out"),
    ("S=`mktemp -d`; rm -rf $S/out", "rm -rf $S/out"),
    # ...and it also forgets whatever the name held before it.
    ("S=/tmp/w; S=$(mktemp -d); rm -rf $S/out", "rm -rf $S/out"),
    # An assignment behind `&&` or `||` may never run, so it is not trusted --
    # and it drops any earlier binding rather than letting a stale one stand.
    ("test -d /tmp/w && S=/tmp/w; rm -rf $S/out", "rm -rf $S/out"),
    ("S=/tmp/w; test -d /x && S=/other; rm -rf $S/out", "rm -rf $S/out"),
    # A name the command never set stays as written.
    ("rm -rf $UNSET/out", "rm -rf $UNSET/out"),
    # A rebinding this pass cannot evaluate drops the earlier value rather than
    # letting it substitute for one the shell has already replaced.
    ("S=/tmp/w; S+=/../../etc; rm -rf $S", "rm -rf $S"),
    ("S=/tmp/w; local S=/other; rm -rf $S", "rm -rf $S"),
    ("S=/tmp/w; { S=/other; }; rm -rf $S", "rm -rf $S"),
    ("S=/tmp/w; unset S; rm -rf $S", "rm -rf $S"),
    ("S=/tmp/w; read S; rm -rf $S", "rm -rf $S"),
    # A value carrying shell syntax is not recorded: substituting it would put
    # that syntax into a clause the caller re-tokenizes.
    ("S='a; b'; rm -rf $S", "rm -rf $S"),
    # An environment prefix sets nothing for a later clause.
    ("S=/tmp/w echo hi; rm -rf $S/out", "rm -rf $S/out"),
    # Inside single quotes a `$` is literal, so there is nothing to resolve.
    ("S=/tmp/w; rm -rf '$S/out'", "rm -rf '$S/out'"),
    # An escaped `\\$` is a literal dollar sign too.
    ("S=/tmp/w; rm -rf \\$S/out", "rm -rf \\$S/out"),
)


@pytest.mark.parametrize(("command", "expected_last"), _UNRESOLVED_CASES)
def test_resolve_assignments_leaves_unresolvable_references_alone(
    command: str, expected_last: str, bash: ModuleType
) -> None:
    """Verify every case the pass declines leaves the reference verbatim.

    An unresolved reference reads as an unknown path to the caller, which is
    the fail-safe direction for a rule that only relaxes on a known-safe path.
    """
    # Given a command whose variable cannot be resolved with certainty
    # When splitting it with assignment resolution
    # Then the final clause still carries the reference as written
    assert bash.resolve_assignments(command)[-1] == expected_last


@pytest.mark.parametrize(
    "command",
    [
        "S=/tmp/w & rm -rf $S/out",
        "S=/tmp/w | rm -rf $S/out",
    ],
    ids=["backgrounded-assignment", "piped-assignment"],
)
def test_resolve_assignments_drops_a_binding_made_in_a_subshell(
    command: str, bash: ModuleType
) -> None:
    """Verify a binding the rest of the command cannot see is not substituted.

    A `|` or `&` behind an assignment runs it in its own shell, so the parent's
    variable stays empty and `$S/out` is really `/out`, not `/tmp/w/out`.
    """
    # Given an assignment the following operator puts in a subshell
    # When splitting the command with assignment resolution
    # Then the later clause keeps the reference as written
    assert bash.resolve_assignments(command, include_pipes=True)[-1] == " rm -rf $S/out"


def test_resolve_assignments_stops_before_an_expansion_bomb(bash: ModuleType) -> None:
    """Verify a chain of doubling assignments cannot make resolution run away.

    Each clause here doubles the value of the last, so an unbudgeted pass grows
    exponentially and a few hundred bytes of command take minutes to resolve.
    """
    # Given a command whose assignments double in length at every clause
    depth = 24
    clauses = ["V0=ab", *(f"V{i}=$V{i - 1}$V{i - 1}" for i in range(1, depth))]
    command = "; ".join(clauses) + f"; rm -rf $V{depth - 1}"

    # When splitting it with assignment resolution
    resolved = bash.resolve_assignments(command)

    # Then the walk gives up rather than materializing the whole expansion
    assert len(resolved[-1]) < 64 * 1024
    assert resolved[-1] == f"rm -rf $V{depth - 1}"


def test_binds_name_reads_only_whole_names(bash: ModuleType) -> None:
    """Verify a suffix of an assigned name is not itself read as bound."""
    # Given a command that binds one name
    command = "TMPDIR=/tmp/w; rm -rf $TMPDIR/out"

    # When asking about that name and about a suffix of it
    # Then only the whole name counts as bound
    assert bash.binds_name(command, "TMPDIR") is True
    assert bash.binds_name(command, "DIR") is False


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("unset TMPDIR; rm -rf $TMPDIR/out", True),
        ("read TMPDIR; rm -rf $TMPDIR/out", True),
        ("rm -rf $TMPDIR/out; unset FOO", False),
    ],
    ids=["unset-the-name", "read-the-name", "unset-an-unrelated-name"],
)
def test_binds_name_confines_a_name_writing_builtin_to_its_own_clause(
    command: str, *, expected: bool, bash: ModuleType
) -> None:
    """Verify an `unset` in one clause does not claim a name used only in another.

    A clause running `unset`/`read` counts every word in it as bound, so the
    scan has to stay inside that clause or an unrelated name goes with it.
    """
    # Given a command whose clauses each mention a different name
    # When asking whether the command binds the name a later clause reads
    # Then only a builtin in the same clause as the name counts
    assert bash.binds_name(command, "TMPDIR") is expected


def test_binds_name_stays_fast_on_a_long_unbroken_word(bash: ModuleType) -> None:
    """Verify a long token cannot stall the scan for bound names.

    The scan is quadratic unless a name has to start at a word boundary, so an
    encoded blob in an `echo` would hold up every Bash tool call behind it.
    """
    # Given a command carrying an 80kB unbroken word
    command = "echo " + "A" * 80_000

    # When asking whether it binds a name
    start = time.perf_counter()
    result = bash.binds_name(command, "TMPDIR")

    # Then the answer is no, and it arrives without a stall
    assert result is False
    assert time.perf_counter() - start < 2


def test_resolve_assignments_matches_split_clauses_without_variables(bash: ModuleType) -> None:
    """Verify resolution is a no-op on a command that references nothing."""
    # Given a command with no variable references
    command = "cd /repo && rm -rf node_modules ; echo 'a && b'"

    # When splitting it both ways
    # Then the clauses are identical
    assert bash.resolve_assignments(command) == bash.split_clauses(command)


# === resolve_command: the same resolution, rebuilt as one command string ===

_UNTOUCHED_COMMANDS: tuple[str, ...] = (
    "echo hello",
    "cd /repo   &&  rm -rf node_modules ;   echo 'a && b'",
    "rm -rf $UNSET/out",
    "a\nb\n\nc",
    "git commit -m 'fix: a=b'",
    "S=$(mktemp -d); rm -rf $S",
)


@pytest.mark.parametrize("command", _UNTOUCHED_COMMANDS)
def test_resolve_command_preserves_a_command_it_cannot_resolve(
    command: str, bash: ModuleType
) -> None:
    """Verify nothing but a resolved reference ever differs from the input.

    A rule matching this text is written against real command syntax, so every
    operator, quote, and run of whitespace has to survive the round trip.
    """
    # Given a command with no reference this pass can resolve
    # When rebuilding it through resolution
    # Then it comes back byte for byte
    assert bash.resolve_command(command) == command


_REBUILT_CASES: tuple[tuple[str, str], ...] = (
    ('D=/etc; rm -rf "$D"', 'D=/etc; rm -rf "/etc"'),
    # A home reference is kept as a spelling the rules already read.
    ('H=$HOME; rm -rf "$H"', 'H=$HOME; rm -rf "$HOME"'),
    ("S=~; rm -rf $S", "S=~; rm -rf ~"),
    # Odd spacing around the operator is part of the text and is preserved.
    ("D=/etc   ;   rm -rf $D", "D=/etc   ;   rm -rf /etc"),
    # Resolution reaches across a clause boundary a per-clause rule cannot.
    ("U=/dev/sda; dd if=/dev/zero of=$U", "U=/dev/sda; dd if=/dev/zero of=/dev/sda"),
)


@pytest.mark.parametrize(("command", "expected"), _REBUILT_CASES)
def test_resolve_command_replays_assignments_across_the_whole_command(
    command: str, expected: str, bash: ModuleType
) -> None:
    """Verify the rebuilt command names the target the shell would act on."""
    # Given a command that binds its target to one of its own variables
    # When rebuilding it through resolution
    # Then the reference is replaced and the rest of the text is untouched
    assert bash.resolve_command(command) == expected


def test_resolve_command_agrees_with_resolve_assignments(bash: ModuleType) -> None:
    """Verify the two entry points share one resolution rather than drifting apart."""
    # Given a command with several assignments and a conditional rebinding
    command = 'A=/tmp/w; B=$A/sub; test -d /x && A=/etc; rm -rf "$B" "$A"'

    # When resolving it as a whole and as clauses
    # Then splitting the whole yields exactly the clauses
    assert bash.split_clauses(bash.resolve_command(command)) == bash.resolve_assignments(command)
