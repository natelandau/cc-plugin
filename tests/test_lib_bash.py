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
