#!/usr/bin/env -S uv run --script

# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///

"""Stop hook: catch ownership-dodging and permission-seeking phrases.

Reads the assistant's most recent message from the JSONL `transcript_path`
provided on the Stop hook's stdin, matches it against a list of phrase
patterns derived from CLAUDE.md golden rules, and on the first match
emits a `{decision: block, reason: ...}` JSON decision. Claude Code
reads the decision and forces the assistant to keep working with the
correction as its next instruction.

`last_assistant_message` does not exist on Stop hook input; the
assistant turn must be recovered by tailing `transcript_path`. Any
code reaching for `last_assistant_message` will silently see an empty
string and never fire.

Violation data lives in `stop_phrase_guard.rules.toml` next to this
file; the script loads it on every invocation. Edit that file to add,
remove, or tune a phrase.
"""

from __future__ import annotations

import json
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from collections.abc import Mapping

RULES_FILE = Path(__file__).parent / "stop_phrase_guard.rules.toml"
VIOLATION_FIELDS = frozenset({"pattern", "correction"})


@dataclass(frozen=True, slots=True)
class Violation:
    """A pattern + correction for the Stop hook to enforce.

    `pattern` is a case-insensitive regex; the first violation that
    matches the assistant's last message wins. `correction` is shown
    to the assistant verbatim (with a `STOP HOOK VIOLATION:` prefix)
    as the reason for blocking the stop.
    """

    pattern: str
    correction: str


def _require_str(entry: Mapping[str, object], key: str, idx: int) -> str:
    """Return entry[key] as a str or raise TypeError naming the offender.

    The TOML loader yields `object`-typed values, so every required field
    is unwrapped through this helper before reaching the Violation
    constructor. Keeps the type narrowing in one place.
    """
    value = entry[key]
    if not isinstance(value, str):
        msg = f"violation[{idx}].{key} must be a string, got {type(value).__name__}"
        raise TypeError(msg)
    return value


def _load_violations(path: Path) -> tuple[tuple[re.Pattern[str], Violation], ...]:
    """Parse the violations TOML and pre-compile each pattern.

    Validate that every entry carries exactly the two required string
    fields, so a typo in TOML surfaces as a clear error instead of a
    Violation built with non-string fields. Patterns are compiled with
    `re.IGNORECASE`.

    Args:
        path: Location of the violations TOML file.

    Returns:
        Pairs of compiled-pattern + Violation in declaration order,
        ready for first-match-wins iteration.
    """
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    entries = data.get("violation")
    if not isinstance(entries, list):
        msg = "missing top-level 'violation' array"
        raise TypeError(msg)
    compiled: list[tuple[re.Pattern[str], Violation]] = []
    for idx, raw_entry in enumerate(entries):
        if not isinstance(raw_entry, dict):
            msg = f"violation[{idx}] is not a table"
            raise TypeError(msg)
        # tomllib types entries as dict[str, Any]; cast to a covariant
        # Mapping so _require_str can read fields without ty rejecting the
        # invariant dict generic.
        entry = cast("Mapping[str, object]", raw_entry)
        keys = entry.keys()
        missing = VIOLATION_FIELDS - keys
        if missing:
            msg = f"violation[{idx}] missing fields: {sorted(missing)}"
            raise ValueError(msg)
        extra = keys - VIOLATION_FIELDS
        if extra:
            msg = f"violation[{idx}] has unexpected fields: {sorted(extra)}"
            raise ValueError(msg)
        violation = Violation(
            pattern=_require_str(entry, "pattern", idx),
            correction=_require_str(entry, "correction", idx),
        )
        compiled.append((re.compile(violation.pattern, re.IGNORECASE), violation))
    return tuple(compiled)


def _last_assistant_text(transcript_path: str) -> str:
    """Return the concatenated text of the most recent assistant turn.

    Each line of the transcript is a JSON object. Assistant turns have
    `type == "assistant"` at the top level and `message.content` as a
    list of blocks; we concatenate `text` from every block whose `type`
    is `text` (skipping `tool_use` blocks).
    """
    try:
        raw = Path(transcript_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""

    for raw_line in reversed(raw.splitlines()):
        line = raw_line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") != "assistant":
            continue
        content = entry.get("message", {}).get("content")
        if not isinstance(content, list):
            continue
        text_parts = [
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        text = "".join(text_parts).strip()
        if text:
            return text
    return ""


def find_violation(
    text: str, compiled: tuple[tuple[re.Pattern[str], Violation], ...]
) -> Violation | None:
    """Return the first violation whose pattern matches the text, or None."""
    for pat, violation in compiled:
        if pat.search(text):
            return violation
    return None


def main() -> None:
    """Entry point for the Stop hook."""
    try:
        data: dict[str, Any] = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    # Already fired once this turn; let the assistant stop to avoid loops.
    if data.get("stop_hook_active"):
        sys.exit(0)

    transcript_path = data.get("transcript_path")
    if not transcript_path:
        sys.exit(0)

    text = _last_assistant_text(transcript_path)
    if not text:
        sys.exit(0)

    # Load violations at invocation, not import, so a malformed TOML
    # surfaces a focused error message rather than a confusing import-time
    # traceback.
    try:
        compiled = _load_violations(RULES_FILE)
    except (OSError, tomllib.TOMLDecodeError, TypeError, ValueError, re.error) as exc:
        print(  # noqa: T201
            f"stop_phrase_guard: failed to load {RULES_FILE.name}: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)

    violation = find_violation(text, compiled)
    if violation is None:
        sys.exit(0)

    decision = {
        "decision": "block",
        "reason": f"STOP HOOK VIOLATION: {violation.correction}",
    }
    print(json.dumps(decision))  # noqa: T201
    sys.exit(0)


if __name__ == "__main__":
    main()
