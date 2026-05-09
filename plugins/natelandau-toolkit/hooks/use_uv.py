#!/usr/bin/env -S uv run --script
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
"""

import json
import re
import sys

# Bash clause separators. Each clause's leading executable is checked
# independently so `cd foo && pytest` still flags the bare pytest.
_CLAUSE_SPLIT = re.compile(r"&&|\|\||[;|&]")

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
    for clause in _CLAUSE_SPLIT.split(command):
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


def main() -> None:
    """Emit a uv suggestion when a bare tool invocation is detected."""
    data = json.load(sys.stdin)

    if data.get("tool_name") != "Bash":
        sys.exit(0)

    command = data.get("tool_input", {}).get("command", "")

    flagged = _flagged(command)
    if flagged is None:
        sys.exit(0)

    old, new = flagged
    # `permissionDecision` is intentionally omitted so the tool call
    # follows the user's normal permission flow rather than auto-allowing.
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": (
                f"Detected '{old}' in command. In uv projects, use '{new}' instead."
            ),
        }
    }
    print(json.dumps(output))  # noqa: T201
    sys.exit(0)


if __name__ == "__main__":
    main()
