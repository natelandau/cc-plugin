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

Alongside splitting, the module resolves the directory a clause acts on --
tracking a leading `cd <dir>` and a git clause's `-C <path>` -- so a hook can
judge each clause against the directory it actually touches instead of wherever
the shell happened to sit.

A hook also sees the command before the shell has expanded anything, so a path
routed through a variable (`S=/tmp/work; rm -rf "$S/out"`) reads as an opaque
token to every path-matching rule. `resolve_assignments` replays the plain
literal assignments a command makes to itself, so those rules judge the path
that will actually be touched.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

from lib.paths import expand_user

# Sequence operators that end one statement and begin the next. A bare newline
# is one of them, so the lines of a multi-line script are separate clauses; a
# `\`-continued or quoted newline is already filler by then and never splits.
# Wrapped in surrounding whitespace so each split part arrives trimmed at the
# boundary.
_SEQUENCE_SPLIT = re.compile(r"\s*(?:&&|\|\||;|\n)\s*")

# Sequence operators plus a single pipe and a background `&`, so each pipeline
# stage and backgrounded command is its own clause.
_PIPELINE_SPLIT = re.compile(r"&&|\|\||[;|&\n]")

# A backslash before a newline continues the same command; the shell removes
# both before parsing. Only a *bare* newline separates statements.
_LINE_CONTINUATION = re.compile(r"\\\r?\n")

# Replaces every quoted or escaped character in mask_quoted's output. A letter
# (never a shell metacharacter or whitespace) so a masked span reads as inert
# word text: operator/redirect scans skip it while token boundaries are kept.
_MASK_FILL = "x"


def join_continuations(command: str) -> str:
    r"""Fold `\`-continued lines into one, the way the shell does before parsing.

    Call this on a command string before matching it, so a rule that scans
    within a single statement is not defeated by splitting the command across
    lines (`git push \<newline>--force`, `rm -rf \<newline>/etc`). Without
    it, every such pattern silently stops at the newline.

    A backslash-newline inside single quotes is literal rather than a
    continuation, so folding it is technically wrong there. It is folded
    anyway: the error direction is a guard matching text it otherwise would
    not, which fails safe, and the alternative is quote-tracking every rule.
    """
    return _LINE_CONTINUATION.sub(" ", command)


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


def _split_with_separators(command: str, pattern: re.Pattern[str]) -> list[tuple[str, str]]:
    """Split `command` on `pattern`, pairing each clause with the operator ahead of it.

    The separator is what `split_clauses` throws away, and it is needed for two
    things: it is the only evidence of whether a clause is certain to run (a
    clause after `;` always executes, one after `&&` or `||` may not), and it
    is what rejoins the clauses into the original string. It is returned
    verbatim, surrounding whitespace included, so a caller that rebuilds the
    command changes nothing but the clauses themselves; strip it before
    comparing it to an operator. The first clause carries an empty separator.
    Operator positions are found on the quote-masked view so a metacharacter
    inside quotes never splits, while the clauses are sliced verbatim out of
    the original string.
    """
    masked = mask_quoted(command)
    parts: list[tuple[str, str]] = []
    last = 0
    separator = ""
    for m in pattern.finditer(masked):
        parts.append((separator, command[last : m.start()]))
        separator = m.group()
        last = m.end()
    parts.append((separator, command[last:]))
    return parts


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
    return [clause for _, clause in _split_with_separators(command, pattern)]


# A shell variable reference, braced or bare. Positional and special parameters
# (`$1`, `$@`, `$?`) are deliberately unmatched: only a name a plain assignment
# could have set is ever resolvable.
_VAR_REF = re.compile(r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))")

# The `NAME=` head of an assignment clause, with the optional `export` prefix.
_ASSIGNMENT_HEAD = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=")

# Separators after which a clause is certain to run. Behind `&&`, `||`, `|` or
# `&` a clause is conditional or concurrent, so an assignment there cannot be
# trusted: if it never runs the variable is empty, and a later command expands
# to a different target than the recorded value predicts.
_UNCONDITIONAL_SEPARATORS = frozenset({"", ";"})

# Separators that put the clause *before* them in a subshell: a pipeline stage
# and a backgrounded command each get their own shell, so a binding either one
# makes never reaches the clauses that follow (`S=/tmp/w & rm -rf $S/out`
# deletes `/out`, not `/tmp/w/out`). Only the pipeline split emits these.
_SUBSHELL_SEPARATORS = frozenset({"|", "&"})

# Characters substitution may add across the whole command. Resolution is
# iterative, so a chain of doubling assignments (`A=ab; B=$A$A; C=$B$B; ...`)
# grows exponentially and a few hundred bytes of command would otherwise take
# minutes. Past the budget every remaining reference is left as written, which
# is the verdict a caller reaches with no resolution at all.
_MAX_EXPANSION_CHARS = 64 * 1024

# Any `NAME=` or `NAME+=` in a clause, wherever it sits. A clause can rebind a
# name in a shape `_ASSIGNMENT_HEAD` does not read as an assignment -- an append
# (`S+=/x`), a keyword-prefixed or block-wrapped one (`local S=/x`, `{ S=/x; }`,
# `then S=/x`) -- and a binding that survived one of those would substitute a
# value the shell has already replaced. Over-matching is harmless: a name this
# finds is only ever forgotten.
#
# The name must start at a word boundary. Without the lookbehind the scan is
# quadratic -- every offset inside a long unbroken word (a base64 blob in an
# `echo`) restarts a greedy run to the end of it looking for an `=` that is not
# there -- so a command of a few tens of kB stalls the hook for tens of seconds.
_REBOUND_NAME = re.compile(r"(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_]*)\+?=")

# Builtins that write a name without an `=` anywhere. Their operands are not
# worth parsing precisely, so any name in such a clause is forgotten.
_NAME_WRITING_BUILTIN = re.compile(r"(?:^|[\s;&|(){])(?:unset|read|mapfile|readarray)(?![\w-])")

_BARE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# A value that is itself the home directory, in a spelling a rule can read.
# `$HOME` is otherwise rejected for carrying a `$`, which would hide the one
# variable whose deletion is catastrophic behind an alias (`H=$HOME; rm -rf
# "$H"`). Substituting it forward keeps the reference a rule already matches.
_HOME_ROOTED = re.compile(r"""(?:~|\$\{?HOME\}?)(?:/[^\s$`;&|<>()'"]*)?""")


def _expand_refs(text: str, values: dict[str, str]) -> str:
    """Substitute `$NAME`/`${NAME}` in `text` from `values`, leaving unknowns as written.

    Quote-aware in the one direction that matters: inside single quotes a `$` is
    literal, so a reference there is left alone rather than resolved to a path
    the shell would never reach. An unknown name is also left as written, which
    keeps it unresolvable to every caller downstream.
    """
    out: list[str] = []
    i = 0
    n = len(text)
    quote = ""
    while i < n:
        ch = text[i]
        if quote == "'":
            out.append(ch)
            if ch == "'":
                quote = ""
            i += 1
            continue
        if ch == "\\" and i + 1 < n:
            # Outside single quotes a backslash escapes the next character, so
            # `\$S` is a literal dollar sign and not a reference.
            out.append(text[i : i + 2])
            i += 2
            continue
        if quote:
            if ch == quote:
                quote = ""
        elif ch in ("'", '"'):
            quote = ch
        if ch == "$":
            m = _VAR_REF.match(text, i)
            if m and (name := m.group(1) or m.group(2)) in values:
                out.append(values[name])
                i = m.end()
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def _literal_word(text: str) -> str | None:
    """Return `text` as one unquoted shell word, or None when it is not literally one.

    None means "do not record this value": the text is several words (an
    environment prefix like `FOO=bar cmd arg`), is unparsable, or carries shell
    syntax this module cannot evaluate or safely substitute (`$(mktemp -d)`, a
    backtick, an unresolved name, an operator). An empty string is a real value
    -- `S=` sets S to empty.
    """
    try:
        words = shlex.split(text)
    except ValueError:
        return None
    if len(words) > 1:
        return None
    word = words[0] if words else ""
    if _HOME_ROOTED.fullmatch(word):
        return word
    # A value is substituted into a later clause that is then re-tokenized, so
    # one carrying shell syntax would be re-read as syntax rather than as the
    # path it stands for.
    return None if any(char in word for char in "$`;&|<>()\n'\"") else word


def _rebound_names(clause: str) -> set[str]:
    """Return every name `clause` might bind, in any spelling this pass cannot evaluate.

    Scanned on the quote-masked view so an `=` inside a quoted argument
    (`git commit -m 'a=b'`) is data, not an assignment.
    """
    masked = mask_quoted(clause)
    names = {m.group(1) for m in _REBOUND_NAME.finditer(masked)}
    if _NAME_WRITING_BUILTIN.search(masked):
        names.update(m.group() for m in _BARE_NAME.finditer(masked))
    return names


def binds_name(command: str, name: str) -> bool:
    """Return whether `command` anywhere binds the shell variable `name`.

    A rule that trusts a reference by its spelling rather than by its value
    (`$TMPDIR/...` as a temp path) must stop trusting it once the command
    rebinds the name, since every later reference then means something else.

    Asked one clause at a time. A clause running `unset`/`read` gives up on
    naming its operands and counts every word in it as bound, so scanning the
    whole command at once would let an `unset` in one clause claim a name that
    only ever appears in another.
    """
    return any(
        name in _rebound_names(clause) for clause in split_clauses(command, include_pipes=True)
    )


def _resolved_parts(command: str, pattern: re.Pattern[str]) -> list[tuple[str, str]]:
    """Split `command` on `pattern`, replaying the literal assignments it makes to itself.

    The shared walk behind `resolve_assignments` and `resolve_command`: it
    carries the value map forward across clauses and returns each clause with
    its references substituted, still paired with its verbatim separator.

    A binding is carried forward only when the clause that makes it is both
    certain to run (the separator ahead of it) and running in this shell rather
    than a subshell (the separator behind it), and only while the command's
    total expansion stays inside `_MAX_EXPANSION_CHARS`.
    """
    values: dict[str, str] = {}
    parts: list[tuple[str, str]] = []
    split = _split_with_separators(command, pattern)
    budget = _MAX_EXPANSION_CHARS
    for position, (separator, clause) in enumerate(split):
        expanded = _expand_refs(clause, values) if values else clause
        budget -= len(expanded) - len(clause)
        if budget < 0:
            values.clear()
            expanded = clause
        parts.append((separator, expanded))
        trailing = split[position + 1][0].strip() if position + 1 < len(split) else ""
        recorded: tuple[str, str] | None = None
        if (
            (m := _ASSIGNMENT_HEAD.match(expanded))
            and separator.strip() in _UNCONDITIONAL_SEPARATORS
            and trailing not in _SUBSHELL_SEPARATORS
        ):
            value = _literal_word(expanded[m.end() :])
            if value is not None:
                recorded = (m.group(1), value)
        # Forget first, then record: every other spelling of a binding drops the
        # name, so only the value this pass evaluated itself survives the clause.
        for name in _rebound_names(expanded):
            values.pop(name, None)
        if recorded:
            values[recorded[0]] = recorded[1]
    return parts


def resolve_assignments(command: str, *, include_pipes: bool = False) -> list[str]:
    """Split `command` into clauses, resolving variables assigned earlier in it.

    Same clauses as `split_clauses`, except that a `$NAME` a preceding clause
    set to a literal value is replaced by that value. A hook sees the command
    before the shell expands anything, so an otherwise inert detour through a
    variable (`S=/tmp/work; rm -rf "$S/out"`) hides the real target from every
    path-matching rule.

    Resolution is deliberately narrow, and every case it declines to resolve
    leaves the reference as written, which reads as an unknown path to the
    caller:

    - Only a clause that is nothing but `NAME=<single literal word>` records a
      value. A value carrying a command substitution, a backtick, or a name
      this pass could not itself resolve records nothing.
    - Only an unconditionally reached assignment (start of the command, or
      after `;` or a newline) is trusted. One behind `&&`/`||` may never run,
      and one followed by `|` or `&` runs in a subshell whose binding the rest
      of the command never sees.
    - A clause that binds a name in any other way *forgets* whatever that name
      held -- an unrecordable value, an append (`S+=/x`), a keyword-prefixed or
      block-wrapped assignment (`local S=/x`), an `unset`/`read`. A stale
      binding can never outlive the clause that replaced it.

    Args:
        command: The Bash command string to split and resolve.
        include_pipes: Also split on a single `|` and a background `&`, as in
            `split_clauses`. Defaults to False.
    """
    pattern = _PIPELINE_SPLIT if include_pipes else _SEQUENCE_SPLIT
    return [clause for _, clause in _resolved_parts(command, pattern)]


def resolve_command(command: str) -> str:
    """Return `command` with its own literal assignments replayed, otherwise verbatim.

    The whole-command counterpart to `resolve_assignments`, for a rule that
    matches across clause boundaries (a remote script piped into a shell) and
    so cannot be handed one clause at a time. Only the resolved references
    differ from the input; every operator, quote and run of whitespace is
    preserved, so a pattern written against real command text still matches.
    """
    return "".join(
        separator + clause for separator, clause in _resolved_parts(command, _SEQUENCE_SPLIT)
    )


# Pulls the `-C <path>` target out of a git clause, so an op is judged against
# the repo it names rather than the shell's cwd. Tolerates the leading
# per-invocation `-c <key=val>` options that may precede `-C`.
_GIT_C_DIR_RE = re.compile(r"\bgit\s+(?:-c\s+\S+\s+)*-C\s+(\S+)")

# A leading `cd <dir>` clause, so an effective cwd can be tracked across
# `cd <dir> && ...`.
_CD_RE = re.compile(r"^\s*cd\s+(\S+)")


def strip_quotes(token: str) -> str:
    """Strip surrounding single/double quotes from a path token captured from a command.

    Command-extracted paths (`git -C '/repo'`, `rm "/repo/f"`) keep their shell
    quotes; without stripping them a path lookup would miss and the caller's
    guard would not see the real target. Paths containing spaces are not
    recovered (the capture regexes stop at the first space); those are a known gap.
    """
    return token.strip("'\"")


def resolve_against(path: str, cwd: str) -> str:
    """Resolve a command-extracted `path` to an absolute string against `cwd` (absolute as-is).

    A leading `~` is expanded first: the hook sees the command before the shell
    has done it, so `~/repo` joined onto `cwd` would name a directory that does
    not exist and every branch or containment lookup on it would come back
    empty.
    """
    expanded = expand_user(strip_quotes(path))
    if expanded.is_absolute():
        return str(expanded)
    return str(Path(cwd) / expanded) if cwd else str(expanded)


def cd_target(clause: str, cwd: str) -> str | None:
    """Return the dir a leading `cd <dir>` clause moves to (resolved against cwd), or None."""
    m = _CD_RE.match(clause)
    return resolve_against(m.group(1), cwd) if m else None


def git_clause_dir(clause: str, cwd: str) -> str:
    """Return the repo dir a git clause operates on, honoring `git -C <path>`.

    Falls back to `cwd` when no `-C` is present, so the op is judged against the
    repo it actually touches rather than wherever git was invoked from.
    """
    m = _GIT_C_DIR_RE.search(clause)
    return resolve_against(m.group(1), cwd) if m else cwd
