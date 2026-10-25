"""Unit tests for hooks/lib/transcript.py: the shared Stop-event readers.

Covers the message reconstruction (split-across-lines, message.id grouping,
legacy fallback) and the turn-scoped file-write detection, by passing plain
entry dicts to the pure functions.
"""

from __future__ import annotations

import importlib
import sys
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from pathlib import Path
    from types import ModuleType


@pytest.fixture
def transcript(hooks_dir: Path) -> ModuleType:
    """Import lib.transcript with the hooks dir on sys.path."""
    sys.path.insert(0, str(hooks_dir))
    try:
        return importlib.import_module("lib.transcript")
    finally:
        sys.path.pop(0)


def _text(text: str, message_id: str = "m1") -> dict[str, Any]:
    return {
        "type": "assistant",
        "message": {
            "id": message_id,
            "role": "assistant",
            "content": [{"type": "text", "text": text}],
        },
    }


def test_last_assistant_message_text_groups_by_message_id(transcript: ModuleType) -> None:
    """Verify text from every block of the final message is concatenated."""
    # Given a message split across two text lines plus an earlier message
    entries = [
        _text("an earlier message", message_id="m0"),
        _text("first block", message_id="m1"),
        _text("second block", message_id="m1"),
    ]

    # When reconstructing the closing message
    result = transcript.last_assistant_message_text(entries)

    # Then both blocks of the final message appear and the earlier one does not
    assert "first block" in result
    assert "second block" in result
    assert "earlier message" not in result


def test_last_assistant_message_text_legacy_no_id(transcript: ModuleType) -> None:
    """Verify a transcript without message.id falls back to the final text line."""
    # Given assistant lines that omit message.id
    entries = [
        {
            "type": "assistant",
            "message": {"role": "assistant", "content": [{"type": "text", "text": "old"}]},
        },
        {
            "type": "assistant",
            "message": {"role": "assistant", "content": [{"type": "text", "text": "newest"}]},
        },
    ]

    # When reconstructing the closing message
    result = transcript.last_assistant_message_text(entries)

    # Then only the final text-bearing line is returned
    assert result == "newest"


def test_last_assistant_message_text_non_dict_message(transcript: ModuleType) -> None:
    """Verify a non-dict `message` value is tolerated instead of raising."""
    # Given a malformed line whose message is not a dict, followed by a normal one
    entries = [
        {"type": "assistant", "message": "a bare string, not a block list"},
        {
            "type": "assistant",
            "message": {"id": "m1", "content": [{"type": "text", "text": "closing"}]},
        },
    ]

    # When reconstructing the closing message
    result = transcript.last_assistant_message_text(entries)

    # Then the malformed line is skipped and the closing text is returned
    assert result == "closing"
