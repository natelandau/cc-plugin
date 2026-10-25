"""Shared transcript-reading helpers for Stop-event hooks.

Stop hook input does NOT carry the assistant text directly; it provides a
`transcript_path` pointing at a JSONL file. Claude Code writes one JSONL
line per content block, so a single assistant message (one `message.id`)
spans several consecutive `type == "assistant"` lines (thinking, text,
tool_use, ...). Any code reaching for a `last_assistant_message` field
will silently see nothing and never fire.

`read_entries` parses the file once into a list of objects; the pure
functions below operate on that list, so every Stop plugin shares a single read.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def parse_stop(payload: dict[str, Any]) -> dict[str, Any]:
    """Read and parse the transcript once, exposing it to every Stop plugin.

    Stop input carries no assistant text directly, only a `transcript_path`.
    Reading and reconstructing the closing message here means each Stop plugin
    sees `assistant_message` and `entries` on its event without re-reading the
    JSONL. The Stop dispatcher passes this as its `prepare` step.
    """
    transcript_path = payload.get("transcript_path")
    entries = read_entries(transcript_path) if transcript_path else []
    return {
        **payload,
        "entries": entries,
        "assistant_message": last_assistant_message_text(entries),
    }


def read_entries(transcript_path: str) -> list[dict[str, Any]]:
    """Parse a JSONL transcript into its object entries, skipping junk lines.

    Blank lines, non-JSON lines, and non-object JSON values are dropped so a
    truncated or partially-flushed transcript never raises. Returns [] when
    the file cannot be read, so callers fail open. The per-hook `timeout` in
    hooks.json bounds a runaway file.
    """
    try:
        raw = Path(transcript_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    entries: list[dict[str, Any]] = []
    for raw_line in raw.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict):
            entries.append(entry)
    return entries


def _assistant_content_blocks(entry: dict[str, Any]) -> list[Any]:
    """Return the `message.content` block list of an assistant entry, else [].

    The shared guard for every reader that walks an assistant turn's blocks: a
    non-assistant entry, a non-dict `message`, or a non-list `content` all
    yield [], so callers iterate without re-checking the entry shape.
    """
    if entry.get("type") != "assistant":
        return []
    message = entry.get("message")
    if not isinstance(message, dict):
        return []
    content = message.get("content")
    return content if isinstance(content, list) else []


def _entry_text(entry: dict[str, Any]) -> str:
    """Concatenate the text of every `text` block in one transcript entry.

    Non-text blocks (`thinking`, `tool_use`) carry no `text` field and
    contribute nothing. Returns "" for non-assistant entries or entries
    whose `message.content` is not a block list.
    """
    return "".join(
        block.get("text", "")
        for block in _assistant_content_blocks(entry)
        if isinstance(block, dict) and block.get("type") == "text"
    )


def last_assistant_message_text(entries: list[dict[str, Any]]) -> str:
    """Return the full text of the most recent assistant message.

    A single assistant message is split across several consecutive
    `type == "assistant"` lines sharing one `message.id`. Collect every
    text-bearing assistant line in transcript order, then concatenate those
    that share the final line's `message.id` so the scan sees the whole
    closing message rather than just its last block.

    Legacy or synthetic transcripts may omit `message.id`; in that case fall
    back to the final text-bearing line alone, since there is no id to group
    on.
    """
    # (message.id, text) for each assistant line that carried any text.
    blocks: list[tuple[object, str]] = []
    for entry in entries:
        text = _entry_text(entry)
        if text.strip():
            # Guard the type like every sibling reader: a non-dict `message`
            # (null/string in a malformed line) would otherwise raise on .get,
            # which the docstring promises never happens.
            message = entry.get("message")
            mid = message.get("id") if isinstance(message, dict) else None
            blocks.append((mid, text))

    if not blocks:
        return ""

    last_id = blocks[-1][0]
    if last_id is None:
        return blocks[-1][1].strip()

    # message.id is unique per message, so filtering the whole list by it is
    # equivalent to taking the final contiguous run of that message.
    parts = [text for mid, text in blocks if mid == last_id]
    return "\n".join(part.strip() for part in parts).strip()
