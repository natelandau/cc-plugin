# plugins/natelandau-toolkit/hooks/lib/transcript.py
"""Shared transcript-reading helpers for Stop-event hooks.

Stop hook input does NOT carry the assistant text directly; it provides a
`transcript_path` pointing at a JSONL file. Claude Code writes one JSONL
line per content block, so a single assistant message (one `message.id`)
spans several consecutive `type == "assistant"` lines (thinking, text,
tool_use, ...). Any code reaching for a `last_assistant_message` field
will silently see nothing and never fire.

`read_entries` parses the file once into a list of objects; the pure
functions below operate on that list so a hook needing both the closing
text and the turn's tool calls reads the file a single time.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator


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


def _is_human_message(entry: dict[str, Any]) -> bool:
    """Return whether an entry is a human turn (not a tool_result user line).

    Human messages carry a string `content`; tool results are recorded as
    user lines whose `content` is a list of `tool_result` blocks. The
    distinction marks where the current turn began.
    """
    if entry.get("type") != "user":
        return False
    message = entry.get("message")
    return isinstance(message, dict) and isinstance(message.get("content"), str)


def entries_since_last_user(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the entries recorded after the most recent human turn.

    Scopes "this turn" to everything the assistant produced since the user
    last spoke, so a check for an action taken this turn does not see actions
    from earlier turns.
    """
    start = 0
    for idx, entry in enumerate(entries):
        if _is_human_message(entry):
            start = idx + 1
    return entries[start:]


def _iter_tool_uses(entry: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Yield each `tool_use` block in one assistant entry, else nothing."""
    if entry.get("type") != "assistant":
        return
    message = entry.get("message")
    if not isinstance(message, dict):
        return
    content = message.get("content")
    if not isinstance(content, list):
        return
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            yield block


def file_written_since_last_user(
    entries: list[dict[str, Any]],
    *,
    filename: str,
    tool_names: frozenset[str],
) -> bool:
    """Return whether a file-writing tool touched `filename` this turn.

    Matches a tool_use whose name is in `tool_names` and whose `file_path`
    (or `notebook_path`) basename equals `filename`. Basename matching keeps
    the check indifferent to whether the model addressed the file by an
    absolute or a relative path.
    """
    for entry in entries_since_last_user(entries):
        for block in _iter_tool_uses(entry):
            if block.get("name") not in tool_names:
                continue
            tool_input = block.get("input")
            if not isinstance(tool_input, dict):
                continue
            path = tool_input.get("file_path") or tool_input.get("notebook_path")
            if isinstance(path, str) and Path(path).name == filename:
                return True
    return False
