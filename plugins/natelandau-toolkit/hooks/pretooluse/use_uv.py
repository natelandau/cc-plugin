#!/usr/bin/env -S uv run --script

# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///

"""PreToolUse nudge: suggest the uv-prefixed form for python/pip/pytest/ruff.

Non-blocking. Emits a `hookSpecificOutput.additionalContext` JSON payload on
stdout (exit 0) when the leading executable of any clause in the bash command
is a bare `python`, `pip install`, `pytest`, or `ruff`. Claude Code injects
that context into the model's next turn, so the model actually sees the
nudge. Earlier versions used `sys.exit(1)` with stderr, but per the hooks
spec exit-1 stderr only reaches the human terminal, not the model, so the
nudge had no effect on Claude's behavior. Substring matching previously
flagged correct usage like `uv run pytest`; clause-aware tokenization
avoids that.

The same nudge is shown at most once per session per suggested tool: the
session-keyed `lib.state` bridge records which suggestions have already
fired so a developer who keeps running bare `pytest` is not re-nudged every
turn. Debouncing is keyed on `session_id`; when the payload carries none (so
there is nothing to key on) the nudge always fires.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from lib import bash, state
from lib.io import Decision

if TYPE_CHECKING:
    from lib.config import Config

ID = "use-uv"

# Maps a bare leading executable to the suggested uv-prefixed form.
_DIRECT_SUGGESTIONS = {
    "python": "uv run python",
    "pytest": "uv run pytest",
    "ruff": "uv run ruff",
}

_ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

# Number of tokens needed to recognize a `pip install ...` invocation.
_PIP_INSTALL_MIN_TOKENS = 2


def _leading_tokens(clause: str) -> list[str]:
    """Return the executable plus its remaining args, after stripping env vars.

    `FOO=bar pytest -v` becomes `["pytest", "-v"]` so the leading executable
    check sees the real command rather than the env assignment.
    """
    tokens = clause.strip().split()
    while tokens and _ENV_ASSIGN.match(tokens[0]):
        tokens.pop(0)
    return tokens


def _flagged(command: str) -> tuple[str, str] | None:
    """Find the first clause whose leading executable is a bare uv-runnable tool."""
    for clause in bash.split_clauses(command, include_pipes=True):
        tokens = _leading_tokens(clause)
        if not tokens:
            continue
        # Path-stripped basename so `/usr/bin/python` still matches `python`.
        head = tokens[0].rsplit("/", 1)[-1]
        if head in _DIRECT_SUGGESTIONS:
            return head, _DIRECT_SUGGESTIONS[head]
        # `pip` is only flagged for the install verb; `pip --version` is fine.
        if head == "pip" and len(tokens) >= _PIP_INSTALL_MIN_TOKENS and tokens[1] == "install":
            return "pip install", "uv add"
    return None


def evaluate(event: dict[str, Any], cfg: Config) -> Decision | None:  # noqa: ARG001
    """Return an advisory Decision nudging toward uv, else None."""
    if event.get("tool_name") != "Bash":
        return None
    command = (event.get("tool_input") or {}).get("command", "")
    flagged = _flagged(command)
    if flagged is None:
        return None
    old, new = flagged
    # Show each tool's nudge once per session; an absent session_id keys to
    # nothing, so should_emit_once returns True and the nudge always fires.
    if not state.should_emit_once(event.get("session_id", ""), f"{ID}:{old}"):
        return None
    return Decision(
        block=False,
        context=f"Detected '{old}' in command. In uv projects, use '{new}' instead.",
    )
