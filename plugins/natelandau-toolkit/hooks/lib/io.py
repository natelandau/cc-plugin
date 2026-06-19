"""Shared I/O helpers for PreToolUse hooks: payload parsing and emission."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import Any, NoReturn


@dataclass(frozen=True, slots=True)
class Decision:
    """Outcome of a single hook check.

    `block=True` halts the tool: `reason` is written to stderr and fed to
    the model. `context` is non-blocking advisory text surfaced to the
    model via `additionalContext`. A check returns `None` (not a Decision)
    when it has nothing to say.
    """

    block: bool
    reason: str = ""
    context: str = ""


def read_payload() -> dict[str, Any]:
    """Parse the hook JSON payload from stdin, or return {} on any error.

    Hooks must never crash on malformed input; an unreadable payload is
    treated as "nothing to act on".
    """
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def emit_block(reason: str) -> NoReturn:
    """Write a block reason to stderr and exit 2 (model-facing block)."""
    print(reason, file=sys.stderr)  # noqa: T201
    sys.exit(2)


def emit_pre_advisory(contexts: list[str]) -> NoReturn:
    """Emit joined advisory context as PreToolUse additionalContext, exit 0.

    With no contexts the hook stays silent (no stdout). Advisory text never
    blocks; it is injected into the model's next turn.
    """
    if contexts:
        payload = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": "\n".join(contexts),
            }
        }
        print(json.dumps(payload))  # noqa: T201
    sys.exit(0)
