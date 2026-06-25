"""Shared Bash command-string tokenization for the Bash-matching hooks.

Several PreToolUse hooks need to split a command into independently-checkable
clauses before applying their rules. They previously each carried their own
split regex, which let the notion of a "clause" drift between hooks. This
module is the single seam, parameterized for the two operator sets the hooks
actually need.
"""

from __future__ import annotations

import re

# Sequence operators that end one statement and begin the next. Wrapped in
# surrounding whitespace so each split part arrives trimmed at the boundary.
_SEQUENCE_SPLIT = re.compile(r"\s*(?:&&|\|\||;)\s*")

# Sequence operators plus a single pipe and a background `&`, so each pipeline
# stage and backgrounded command is its own clause.
_PIPELINE_SPLIT = re.compile(r"&&|\|\||[;|&]")


def split_clauses(command: str, *, include_pipes: bool = False) -> list[str]:
    """Split a Bash command into independently-checkable clauses.

    Use to apply a per-command rule to each part of a compound command in
    isolation, so an operator chain cannot smuggle a clause past a check.

    By default splits on the sequence operators `&&`, `||`, `;` (where one
    statement ends and the next begins). With `include_pipes=True` it also
    splits on a single `|` and a background `&`, so each pipeline stage and
    backgrounded command becomes its own clause -- needed when the leading
    executable of every stage matters, not just every statement.

    Parts are returned verbatim (callers strip as needed); an operator-only or
    empty segment yields an empty-string clause, matching `re.split`.
    """
    pattern = _PIPELINE_SPLIT if include_pipes else _SEQUENCE_SPLIT
    return pattern.split(command)
