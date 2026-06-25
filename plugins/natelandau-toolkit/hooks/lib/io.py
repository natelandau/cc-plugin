"""Shared I/O helpers for hook stages: payload parsing and per-stage emission."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, NoReturn

if TYPE_CHECKING:
    from collections.abc import Callable

# Upper bound on stdin we will parse. Sized generously so legitimate large
# payloads (e.g. a `Write` carrying a sizable file `content`) are still
# inspected by the guards, while a pathological or truncated stream cannot
# be read unbounded into memory. The dispatcher's per-hook `timeout` in
# hooks.json is the primary guard against a never-ending stream; this cap
# is a memory backstop. Oversized input fails open (returns {}, "nothing to
# act on") to honor the never-crash contract; the cap is far above any real
# tool payload, so only malformed input reaches it.
MAX_STDIN_BYTES = 10 * 1024 * 1024


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

    @classmethod
    def blocked(cls, hook_id: str, message: str) -> Decision:
        """Construct a blocking Decision with the canonical reason prefix.

        Every guard fronts its reason with `BLOCKED [<hook_id>]: ` so the
        model sees one uniform, greppable block format carrying the slug a
        user would put in `disabled_hooks`. `message` is the hook-specific
        remainder. Centralizing the prefix keeps every guard that blocks
        from drifting in wording.
        """
        return cls(block=True, reason=f"BLOCKED [{hook_id}]: {message}")


def read_payload() -> dict[str, Any]:
    """Parse the hook JSON payload from stdin, or return {} on any error.

    Hooks must never crash on malformed input; an unreadable, oversized, or
    non-object payload is treated as "nothing to act on". Reads at most
    `MAX_STDIN_BYTES + 1` characters so a truncated or runaway stream is
    rejected outright rather than parsed into a possibly-misleading partial.
    """
    try:
        raw = sys.stdin.read(MAX_STDIN_BYTES + 1)
    except OSError, ValueError, UnicodeDecodeError:
        return {}
    if len(raw) > MAX_STDIN_BYTES:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError, ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def emit_block(reason: str) -> NoReturn:
    """Write a block reason to stderr and exit 2 (model-facing block)."""
    print(reason, file=sys.stderr)  # noqa: T201
    sys.exit(2)


def _emit_advisory(contexts: list[str], event_name: str) -> NoReturn:
    """Emit joined advisory text as this stage's additionalContext, exit 0."""
    if contexts:
        payload = {
            "hookSpecificOutput": {
                "hookEventName": event_name,
                "additionalContext": "\n".join(contexts),
            }
        }
        print(json.dumps(payload))  # noqa: T201
    sys.exit(0)


def emit_pretooluse(blocking: Decision | None, contexts: list[str]) -> NoReturn:
    """Translate a PreToolUse outcome: block via exit 2, else advisory context."""
    if blocking is not None:
        emit_block(blocking.reason)  # exits 2
    _emit_advisory(contexts, "PreToolUse")


def emit_posttooluse(blocking: Decision | None, contexts: list[str]) -> NoReturn:
    """Translate a PostToolUse outcome: the tool already ran, so block is JSON."""
    if blocking is not None:
        payload = {
            "hookSpecificOutput": {"hookEventName": "PostToolUse", "decision": "block"},
            "reason": blocking.reason,
        }
        print(json.dumps(payload))  # noqa: T201
        sys.exit(0)
    _emit_advisory(contexts, "PostToolUse")


def emit_stop(blocking: Decision | None, contexts: list[str]) -> NoReturn:  # noqa: ARG001
    """Translate a Stop outcome: block prevents stopping via decision JSON."""
    if blocking is not None:
        print(json.dumps({"decision": "block", "reason": blocking.reason}))  # noqa: T201
    sys.exit(0)


def emit_sessionstart(blocking: Decision | None, contexts: list[str]) -> NoReturn:  # noqa: ARG001
    """Translate a SessionStart outcome: advisory context only; block is N/A."""
    _emit_advisory(contexts, "SessionStart")


def emit_sessionend(blocking: Decision | None, contexts: list[str]) -> NoReturn:  # noqa: ARG001
    """SessionEnd is read-only for side effects; emit nothing and exit 0."""
    sys.exit(0)


# Maps a stage name to the emitter that translates its outcome to the wire
# format. One table the dispatcher driver indexes by stage, so a stage's name
# and its emit function are related by data rather than a per-script import.
STAGE_EMITTERS: dict[str, Callable[[Decision | None, list[str]], NoReturn]] = {
    "pretooluse": emit_pretooluse,
    "posttooluse": emit_posttooluse,
    "stop": emit_stop,
    "sessionstart": emit_sessionstart,
    "sessionend": emit_sessionend,
}
