"""Shared Bash command-string tokenization for the Bash-matching hooks.

Several PreToolUse hooks need to split a command into independently-checkable
clauses before applying their rules. They previously each carried their own
split regex, which let the notion of a "clause" drift between hooks. This
module is the single seam, parameterized for the two operator sets the hooks
actually need.

Splitting is quote-aware: a `&&`, `;`, `|`, or redirect `>` that lives inside
single or double quotes (an `awk 'c>=2'` program, an `echo "a && b"` literal)
is data, not shell syntax, so it must not split a clause or read as a redirect.
`mask_quoted` neutralizes those quoted spans while preserving every byte offset,
so the split regexes match only real operators yet the parts stay verbatim.
"""

from __future__ import annotations

import re

# Sequence operators that end one statement and begin the next. Wrapped in
# surrounding whitespace so each split part arrives trimmed at the boundary.
_SEQUENCE_SPLIT = re.compile(r"\s*(?:&&|\|\||;)\s*")

# Sequence operators plus a single pipe and a background `&`, so each pipeline
# stage and backgrounded command is its own clause.
_PIPELINE_SPLIT = re.compile(r"&&|\|\||[;|&]")

# Replaces every quoted or escaped character in mask_quoted's output. A letter
# (never a shell metacharacter or whitespace) so a masked span reads as inert
# word text: operator/redirect scans skip it while token boundaries are kept.
_MASK_FILL = "x"


def mask_quoted(command: str) -> str:
    """Return command with quoted and escaped spans overwritten by a neutral filler.

    Single-quoted, double-quoted, and backslash-escaped characters are each
    replaced one-for-one with a filler letter, preserving the string's length
    and every byte offset. Scan this masked view for shell operators or
    redirects so a metacharacter that is really quoted data (`awk 'c>=2'`,
    `echo "a && b"`, `grep 'a>b'`) is never mistaken for syntax. Because offsets
    map 1:1 back to `command`, a match found on the masked view can be sliced
    straight out of the original string.

    Args:
        command: The Bash command string to mask.
    """
    out = list(command)
    i = 0
    n = len(command)
    quote = ""  # the open quote char while inside a quote, else ""
    while i < n:
        ch = command[i]
        if quote:
            out[i] = _MASK_FILL
            # Inside double quotes a backslash escapes the next char, so an
            # escaped quote does not close the string. Single quotes have no
            # escape mechanism, so only honor it inside double quotes.
            if quote == '"' and ch == "\\" and i + 1 < n:
                out[i + 1] = _MASK_FILL
                i += 2
                continue
            if ch == quote:
                quote = ""
            i += 1
            continue
        if ch == "\\" and i + 1 < n:
            # An unquoted backslash escapes the next char, making it literal.
            out[i] = _MASK_FILL
            out[i + 1] = _MASK_FILL
            i += 2
            continue
        if ch in ("'", '"'):
            quote = ch
            out[i] = _MASK_FILL
            i += 1
            continue
        i += 1
    return "".join(out)


# Suppression-context stack frames: True suppresses `>`/`<` (arithmetic or test),
# False scans them (command substitution / subshell). Innermost frame wins.
_Context = list[bool]

# Reserved words after which a `[[` is the test keyword (a command position), not
# a literal argument. Control operators are handled separately by the char check.
_CMD_POS_WORDS = frozenset({"if", "then", "elif", "else", "while", "until", "do", "time", "!"})


def _at_command_position(masked: str, i: int) -> bool:
    """Return whether index `i` in `masked` starts a shell command.

    `[[` is the test keyword only in command position -- the start of the string,
    just after a control operator (`; & | ( { newline`), or after a reserved word
    like `if`/`while`. As a plain argument (`echo [[`) it is an ordinary word, and
    opening a test context there would mask a real redirect that follows it.
    """
    j = i - 1
    while j >= 0 and masked[j] in " \t":
        j -= 1
    if j < 0 or masked[j] in ";&|(){\n":
        return True
    k = j
    while k >= 0 and masked[k] not in " \t;&|(){\n":
        k -= 1
    return masked[k + 1 : j + 1] in _CMD_POS_WORDS


def _open_context_token(masked: str, i: int, stack: _Context) -> int:
    """Advance `stack` past a multi-char context token at `i`; return its width, else 0.

    `$((` and `((` open arithmetic (two parens -> two suppress frames, closed by
    the two `)` of `))`); a bare `((` is arithmetic only at top level or already
    inside arithmetic, else it is two subshells. `$(` opens a scanned command
    substitution. `[[`/`]]` open and close a test, but `[[` opens one only as a
    command-position keyword (so `echo [[ > f` keeps its real redirect visible).
    A return of 0 means `masked[i]` is a plain character.
    """
    if masked.startswith("$((", i):
        stack.extend((True, True))
        return 3
    two = masked[i : i + 2]
    if two == "((" and (not stack or stack[-1]):
        stack.extend((True, True))
        return 2
    if two == "$(":
        stack.append(False)
        return 2
    if (
        two == "[["
        and (i + 2 >= len(masked) or masked[i + 2] in " \t")
        and _at_command_position(masked, i)
    ):
        stack.append(True)
        return 2
    if two == "]]":
        if stack:
            stack.pop()
        return 2
    return 0


def mask_comparisons(masked: str) -> str:
    """Blank `>`/`<` that are comparison operators, not redirects.

    Inside an arithmetic `(( ))` / `$(( ))` or a `[[ ]]` test, `>` and `<`
    compare values; they never redirect. Pass an already quote-masked string
    (see `mask_quoted`) and they are overwritten with filler so a redirect scan
    skips them, fixing false positives like `[[ 5 > 3 ]]` and `(( a > b ))`.

    Crucially, command substitutions `$( )`, backtick substitutions, and plain
    subshells `( )` are SCAN regions, not suppressed: their bodies execute, so a
    `>` inside one is a real redirect and is left intact. Suppression follows the
    innermost context, so a `$( cat x > f )` nested inside `(( ))` still exposes
    its redirect -- a write can never be hidden by wrapping it in arithmetic.

    Args:
        masked: A command string already run through `mask_quoted`, so quoted
            parens and operators are filler and only real syntax is scanned.
    """
    out = list(masked)
    stack: _Context = []
    i = 0
    n = len(masked)
    while i < n:
        width = _open_context_token(masked, i, stack)
        if width:
            i += width
            continue
        ch = masked[i]
        if ch == "`":
            # Backtick command substitution toggles a scan context.
            if stack and stack[-1] is False:
                stack.pop()
            else:
                stack.append(False)
        elif ch == "(":
            # A lone paren is arithmetic grouping inside arithmetic, else a subshell.
            stack.append(bool(stack) and stack[-1])
        elif ch == ")" and stack:
            stack.pop()
        elif ch in "<>" and stack and stack[-1]:
            out[i] = _MASK_FILL
        i += 1
    return "".join(out)


def split_clauses(command: str, *, include_pipes: bool = False) -> list[str]:
    """Split a Bash command into independently-checkable clauses.

    Use to apply a per-command rule to each part of a compound command in
    isolation, so an operator chain cannot smuggle a clause past a check.

    By default splits on the sequence operators `&&`, `||`, `;` (where one
    statement ends and the next begins). With `include_pipes=True` it also
    splits on a single `|` and a background `&`, so each pipeline stage and
    backgrounded command becomes its own clause -- needed when the leading
    executable of every stage matters, not just every statement.

    Splitting is quote-aware: an operator inside single or double quotes is
    data, not syntax, so it never splits (an `awk '... || ...'` program stays
    one clause). Split *points* are found on a quote-masked view, but the parts
    are sliced verbatim from the original (callers strip as needed); an
    operator-only or empty segment yields an empty-string clause, matching the
    `re.split` the masked scan mirrors.

    Args:
        command: The Bash command string to split.
        include_pipes: Also split on a single `|` and a background `&`, not
            just the sequence operators. Defaults to False.
    """
    pattern = _PIPELINE_SPLIT if include_pipes else _SEQUENCE_SPLIT
    # Match operator positions on the quote-masked view so a `&&`/`;`/`|` inside
    # quotes never splits, then slice the parts out of the original string -- the
    # parts stay byte-for-byte verbatim, only the split points are quote-aware.
    masked = mask_quoted(command)
    parts: list[str] = []
    last = 0
    for m in pattern.finditer(masked):
        parts.append(command[last : m.start()])
        last = m.end()
    parts.append(command[last:])
    return parts
