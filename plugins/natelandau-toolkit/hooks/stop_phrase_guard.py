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

Claude Code writes one JSONL line per content block, so a single
assistant message (one `message.id`) spans several consecutive
`type == "assistant"` lines (thinking, text, tool_use, ...). Reading
only the final line would inspect just the last block and miss a
violation in an earlier text block of the same message. The scan
therefore reconstructs the most recent assistant *message* by
concatenating the text of every line sharing its `message.id`.

Violation data lives in `stop_phrase_guard.rules.toml` next to this
file; the script loads it on every invocation. Edit that file to add,
remove, or tune a phrase.
"""

from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

from lib import rules
from lib.config import load_config
from lib.io import read_payload
from lib.registry import hook_enabled

RULES_FILE = Path(__file__).parent / "stop_phrase_guard.rules.toml"
# Each [[violation]] needs a `reason` (shown to the assistant as the block
# correction); `id` is optional and unused in the output message.
STOP_REQUIRED = frozenset({"reason"})
STOP_OPTIONAL = frozenset({"id"})


def _entry_text(entry: dict[str, Any]) -> str:
    """Concatenate the text of every `text` block in one transcript entry.

    Non-text blocks (`thinking`, `tool_use`) carry no `text` field and
    contribute nothing. Returns "" for non-assistant entries or entries
    whose `message.content` is not a block list.
    """
    if entry.get("type") != "assistant":
        return ""
    message = entry.get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if not isinstance(content, list):
        return ""
    return "".join(
        block.get("text", "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    )


def _last_assistant_message_text(transcript_path: str) -> str:
    """Return the full text of the most recent assistant message.

    Claude Code writes one JSONL line per content block, so a single
    assistant message is split across several consecutive
    `type == "assistant"` lines sharing one `message.id`. Collect every
    text-bearing assistant line in transcript order, then concatenate
    those that share the final line's `message.id` so the scan sees the
    whole closing message rather than just its last block.

    Legacy or synthetic transcripts may omit `message.id`; in that case
    fall back to the final text-bearing line alone, since there is no id
    to group on.
    """
    try:
        raw = Path(transcript_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""

    # (message.id, text) for each assistant line that carried any text.
    blocks: list[tuple[object, str]] = []
    for raw_line in raw.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        text = _entry_text(entry)
        if text.strip():
            message = entry.get("message", {})
            blocks.append((message.get("id"), text))

    if not blocks:
        return ""

    last_id = blocks[-1][0]
    if last_id is None:
        return blocks[-1][1].strip()

    # message.id is unique per message, so filtering the whole list by it
    # is equivalent to taking the final contiguous run of that message.
    parts = [text for mid, text in blocks if mid == last_id]
    return "\n".join(part.strip() for part in parts).strip()


def main() -> None:
    """Entry point for the Stop hook."""
    # Shared capped reader: bounds stdin and fails open to {} on malformed,
    # oversized, or non-object input (the guards below then no-op via .get()).
    data: dict[str, Any] = read_payload()

    # Already fired once this turn; let the assistant stop to avoid loops.
    if data.get("stop_hook_active"):
        sys.exit(0)

    transcript_path = data.get("transcript_path")
    if not transcript_path:
        sys.exit(0)

    cfg = load_config()
    if not hook_enabled("stop-phrase-guard", cfg):
        sys.exit(0)

    text = _last_assistant_message_text(transcript_path)
    if not text:
        sys.exit(0)

    # Load violations at invocation, not import, so a malformed TOML
    # surfaces a focused error message rather than a confusing import-time
    # traceback.
    try:
        violations = rules.load_rules(
            RULES_FILE, "violation", required=STOP_REQUIRED, optional=STOP_OPTIONAL
        )
    except (OSError, tomllib.TOMLDecodeError, TypeError, ValueError, re.error) as exc:
        print(  # noqa: T201
            f"stop_phrase_guard: failed to load {RULES_FILE.name}: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)

    # `text` is the primary match text; also expose it as the named field
    # `message` so a rule may target it explicitly with `field = "message"`.
    violation = rules.first_match(violations, text=text, fields={"message": text})
    if violation is None:
        sys.exit(0)

    decision = {
        "decision": "block",
        "reason": f"STOP HOOK VIOLATION: {violation.reason}",
    }
    print(json.dumps(decision))  # noqa: T201
    sys.exit(0)


if __name__ == "__main__":
    main()
