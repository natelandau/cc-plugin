"""PreToolUse nudge: suggest the uv-prefixed form for tools the project venv provides.

Non-blocking. Emits a `hookSpecificOutput.additionalContext` JSON payload on
stdout (exit 0) when the leading executable of any clause in the bash command
is a bare `python`, `pytest`, or `ruff` that the project's own virtualenv
provides, or a bare `pip install` inside a project that has a virtualenv.
Claude Code injects that context into the model's next turn, so the model
actually sees the nudge. (Exit-1 stderr only reaches the human terminal, not
the model, so it is useless for a nudge.) Matching is clause-aware so correct
usage like `uv run pytest` is never flagged.

The gate is the project venv, not the tool name: `uv run` exists to run the
project-pinned version of a tool, so a bare name only earns a nudge when
`.venv/bin/<tool>` exists at or above the command's effective cwd (`cd`
clauses move it). A tool the venv lacks resolves to the user's PATH, e.g. a
`uv tool install`ed `ruff` in `~/.local/bin`, and invoking it bare is the
right call. An explicitly path-qualified executable (`~/.local/bin/ruff`,
`/usr/bin/python`, `.venv/bin/pytest`) is a deliberate choice of binary and
is never nudged. A payload with no cwd cannot locate a project and stays
silent.

The same nudge is shown at most once per session per suggested tool: the
session-keyed `lib.state` bridge records which suggestions have already
fired so a developer who keeps running bare `pytest` is not re-nudged every
turn. Debouncing is keyed on `session_id`; when the payload carries none (so
there is nothing to key on) the nudge always fires.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
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


def _project_venv(cwd: str) -> Path | None:
    """Return the nearest `.venv` at or above `cwd`, or None when there is none.

    Mirrors uv's own project discovery, which walks up from the cwd, so a
    command run from a subdirectory is still judged against the project venv.
    """
    if not cwd:
        return None
    # Lexical normalization, matching bash's logical `cd`: a `..` left in an
    # effective cwd would otherwise walk back into the directory just left.
    start = Path(os.path.normpath(cwd))
    for directory in (start, *start.parents):
        venv = directory / ".venv"
        if (venv / "pyvenv.cfg").is_file():
            return venv
    return None


def _suggestion(tokens: list[str], venv: Path) -> tuple[str, str] | None:
    """Return (flagged form, uv form) for a bare tool `venv` provides, else None."""
    head = tokens[0]
    # A path-qualified executable is a deliberate choice of binary.
    if "/" in head:
        return None
    if head in _DIRECT_SUGGESTIONS and (venv / "bin" / head).is_file():
        return head, _DIRECT_SUGGESTIONS[head]
    # `pip` is only flagged for the install verb; `pip --version` is fine.
    if head == "pip" and len(tokens) >= _PIP_INSTALL_MIN_TOKENS and tokens[1] == "install":
        return "pip install", "uv add"
    return None


def _flagged(command: str, cwd: str) -> tuple[str, str] | None:
    """Find the first clause whose leading executable is a bare venv-provided tool."""
    eff_cwd = cwd
    for clause in bash.split_clauses(command, include_pipes=True):
        moved = bash.cd_target(clause, eff_cwd)
        if moved:
            eff_cwd = moved
            continue
        tokens = _leading_tokens(clause)
        if not tokens:
            continue
        venv = _project_venv(eff_cwd)
        if venv is None:
            continue
        suggestion = _suggestion(tokens, venv)
        if suggestion:
            return suggestion
    return None


def evaluate(event: dict[str, Any], cfg: Config) -> Decision | None:  # noqa: ARG001
    """Return an advisory Decision nudging toward uv, else None."""
    if event.get("tool_name") != "Bash":
        return None
    command = (event.get("tool_input") or {}).get("command", "")
    flagged = _flagged(command, event.get("cwd", ""))
    if flagged is None:
        return None
    old, new = flagged
    # Show each tool's nudge once per session; an absent session_id keys to
    # nothing, so should_emit_once returns True and the nudge always fires.
    if not state.should_emit_once(event.get("session_id", ""), f"{ID}:{old}"):
        return None
    if old == "pip install":
        context = (
            "Detected 'pip install' in a uv project. Use 'uv add' so the dependency "
            "lands in pyproject.toml and the lockfile, not just the venv."
        )
    else:
        context = (
            f"Detected '{old}' in command. This project's .venv provides it, "
            f"so use '{new}' to run the project-pinned version."
        )
    return Decision(block=False, context=context)
