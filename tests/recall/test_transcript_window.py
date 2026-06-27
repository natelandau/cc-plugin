"""Verify transcript windowing and noise filtering for the recall sweep."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path
    from types import ModuleType


# ---------------------------------------------------------------------------
# Entry-building helpers (mirror the JSONL shape produced by Claude Code)
# ---------------------------------------------------------------------------


def _user(text: str) -> dict:
    """Build a user entry with a plain-string content field."""
    return {"type": "user", "message": {"role": "user", "content": text}}


def _assistant(text: str, msg_id: str = "msg_a") -> dict:
    """Build an assistant entry with a single text block."""
    return {
        "type": "assistant",
        "message": {
            "id": msg_id,
            "role": "assistant",
            "content": [{"type": "text", "text": text}],
        },
    }


def _tool_result_user() -> dict:
    """Build a user entry whose content is a list of tool_result blocks (not human text)."""
    return {
        "type": "user",
        "message": {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "tu_1", "content": "ok"}],
        },
    }


def _thinking_assistant() -> dict:
    """Build an assistant entry containing only a thinking block (no text)."""
    return {
        "type": "assistant",
        "message": {
            "id": "msg_think",
            "role": "assistant",
            "content": [{"type": "thinking", "thinking": "reasoning here"}],
        },
    }


def _compact(boundary_type: str = "type") -> dict:
    """Build a compact-boundary entry using the given shape.

    boundary_type:
        'type'    -> {"type": "compact_boundary"}
        'flag'    -> {"isCompactSummary": True}
        'field'   -> {"compact_boundary": True}
    """
    if boundary_type == "type":
        return {"type": "compact_boundary", "summary": "..."}
    if boundary_type == "flag":
        return {"type": "summary", "isCompactSummary": True}
    # "field"
    return {"type": "summary", "compact_boundary": True}


# ---------------------------------------------------------------------------
# window_since_compact tests
# ---------------------------------------------------------------------------


def test_window_since_compact_drops_up_to_and_including_boundary(
    load_recall_module: Callable[..., ModuleType],
) -> None:
    """Verify window excludes everything up to and including the boundary entry."""
    # Given entries with one compact boundary in the middle
    transcript = load_recall_module("lib", "transcript.py")
    before = [_user("pre-compact message"), _assistant("pre-compact reply")]
    boundary = _compact("type")
    after = [_user("post-compact message"), _assistant("post-compact reply")]
    entries = [*before, boundary, *after]

    # When windowing since the last compact boundary
    result = transcript.window_since_compact(entries)

    # Then only post-boundary entries are returned
    assert result == after


def test_window_since_compact_uses_last_boundary(
    load_recall_module: Callable[..., ModuleType],
) -> None:
    """Verify window uses the *last* compact boundary when multiple are present."""
    # Given two compact boundaries
    transcript = load_recall_module("lib", "transcript.py")
    entries = [
        _user("oldest"),
        _compact("type"),
        _user("middle"),
        _compact("flag"),
        _user("newest"),
    ]

    # When windowing
    result = transcript.window_since_compact(entries)

    # Then only the entries after the second boundary are returned
    assert len(result) == 1
    assert result[0]["message"]["content"] == "newest"


def test_window_since_compact_no_boundary_returns_all(
    load_recall_module: Callable[..., ModuleType],
) -> None:
    """Verify all entries are returned when no compact boundary is present."""
    # Given entries with no compact boundary
    transcript = load_recall_module("lib", "transcript.py")
    entries = [_user("hello"), _assistant("hi"), _user("bye")]

    # When windowing
    result = transcript.window_since_compact(entries)

    # Then all entries are returned unchanged
    assert result == entries


@pytest.mark.parametrize("btype", ["type", "flag", "field"])
def test_window_since_compact_recognizes_all_boundary_shapes(
    btype: str,
    load_recall_module: Callable[..., ModuleType],
) -> None:
    """Verify all three compact-boundary field shapes are recognized."""
    # Given a boundary of each shape with trailing content
    transcript = load_recall_module("lib", "transcript.py")
    entries = [_user("before"), _compact(btype), _user("after")]

    # When windowing
    result = transcript.window_since_compact(entries)

    # Then only the post-boundary entry is returned
    assert len(result) == 1
    assert result[0]["message"]["content"] == "after"


def test_window_since_compact_boundary_at_end_returns_empty(
    load_recall_module: Callable[..., ModuleType],
) -> None:
    """Verify an empty list is returned when the boundary is the last entry."""
    # Given a boundary with nothing after it
    transcript = load_recall_module("lib", "transcript.py")
    entries = [_user("message"), _compact("type")]

    # When windowing
    result = transcript.window_since_compact(entries)

    # Then nothing is returned
    assert result == []


# ---------------------------------------------------------------------------
# meaningful_messages tests
# ---------------------------------------------------------------------------


def test_meaningful_messages_passes_normal_exchange(
    load_recall_module: Callable[..., ModuleType],
) -> None:
    """Verify a normal user/assistant exchange is kept intact."""
    # Given a simple user + assistant turn
    transcript = load_recall_module("lib", "transcript.py")
    entries = [_user("Can you help?"), _assistant("Sure, here is what to do.")]

    # When filtering meaningful messages
    result = transcript.meaningful_messages(entries)

    # Then both entries are returned
    assert result == entries


@pytest.mark.parametrize(
    "noise_text",
    [
        "<system-reminder>content</system-reminder>",
        "Stop hook feedback: the model ignored the backlog",
        "<command-name>my-skill</command-name>",
        "<recall-memory>previous learnings</recall-memory>",
        "<local-command-caveat>something</local-command-caveat>",
        "<local-command-stdout>output</local-command-stdout>",
        "<command-message>run this</command-message>",
        "<command-args>--flag</command-args>",
        "<task-notification>task done</task-notification>",
        "SessionStart hook additional context: here",
        "Base directory for this skill: /foo",
    ],
)
def test_meaningful_messages_filters_noise_markers(
    noise_text: str,
    load_recall_module: Callable[..., ModuleType],
) -> None:
    """Verify entries whose text contains any NOISE_MARKER are excluded."""
    # Given a user entry with a noise marker in its text
    transcript = load_recall_module("lib", "transcript.py")
    entries = [_user(noise_text)]

    # When filtering meaningful messages
    result = transcript.meaningful_messages(entries)

    # Then the noisy entry is excluded
    assert result == []


def test_meaningful_messages_drops_tool_result_user(
    load_recall_module: Callable[..., ModuleType],
) -> None:
    """Verify user entries whose content is a list (tool_result) are dropped."""
    # Given a tool-result user line
    transcript = load_recall_module("lib", "transcript.py")
    entries = [_tool_result_user()]

    # When filtering
    result = transcript.meaningful_messages(entries)

    # Then the tool-result entry is excluded (content is a list, not a string)
    assert result == []


def test_meaningful_messages_drops_thinking_only_assistant(
    load_recall_module: Callable[..., ModuleType],
) -> None:
    """Verify assistant entries with only a thinking block and no text are dropped."""
    # Given an assistant entry with a thinking block but no text block
    transcript = load_recall_module("lib", "transcript.py")
    entries = [_thinking_assistant()]

    # When filtering
    result = transcript.meaningful_messages(entries)

    # Then the pure-thinking entry is excluded
    assert result == []


def test_meaningful_messages_drops_non_user_assistant_entries(
    load_recall_module: Callable[..., ModuleType],
) -> None:
    """Verify entries of other types (system, compact_boundary) are excluded."""
    # Given entries of various non-user/assistant types
    transcript = load_recall_module("lib", "transcript.py")
    entries = [
        {"type": "system", "message": {"content": "a system note"}},
        _compact("type"),
        _user("real message"),
    ]

    # When filtering
    result = transcript.meaningful_messages(entries)

    # Then only the real user message is kept
    assert len(result) == 1
    assert result[0]["message"]["content"] == "real message"


def test_meaningful_messages_mixed_noise_and_clean(
    load_recall_module: Callable[..., ModuleType],
) -> None:
    """Verify noise entries are removed while clean entries are preserved."""
    # Given a mix of noisy and clean entries
    transcript = load_recall_module("lib", "transcript.py")
    clean_user = _user("What time is it?")
    noisy_user = _user("<system-reminder>remember this</system-reminder>")
    clean_assistant = _assistant("It is noon.")
    noisy_assistant = _assistant("Stop hook feedback: ignored backlog")

    entries = [clean_user, noisy_user, clean_assistant, noisy_assistant]

    # When filtering
    result = transcript.meaningful_messages(entries)

    # Then only the two clean entries remain
    assert result == [clean_user, clean_assistant]


# ---------------------------------------------------------------------------
# read_entries tests (smoke-check the verbatim copy)
# ---------------------------------------------------------------------------


def test_read_entries_parses_jsonl(
    load_recall_module: Callable[..., ModuleType],
    tmp_path: Path,
) -> None:
    """Verify read_entries parses a well-formed JSONL file into a list of dicts."""
    # Given a JSONL file with two entries
    transcript = load_recall_module("lib", "transcript.py")
    f = tmp_path / "t.jsonl"
    e1 = _user("hello")
    e2 = _assistant("world")
    f.write_text(json.dumps(e1) + "\n" + json.dumps(e2) + "\n", encoding="utf-8")

    # When reading
    result = transcript.read_entries(str(f))

    # Then both entries are returned
    assert result == [e1, e2]


def test_read_entries_returns_empty_on_missing_file(
    load_recall_module: Callable[..., ModuleType],
    tmp_path: Path,
) -> None:
    """Verify read_entries returns [] rather than raising when the file is absent."""
    # Given a path that does not exist
    transcript = load_recall_module("lib", "transcript.py")

    # When reading a missing file
    result = transcript.read_entries(str(tmp_path / "nonexistent.jsonl"))

    # Then an empty list is returned (fail-open)
    assert result == []


def test_read_entries_skips_blank_and_invalid_lines(
    load_recall_module: Callable[..., ModuleType],
    tmp_path: Path,
) -> None:
    """Verify malformed or blank JSONL lines are skipped without error."""
    # Given a file with a valid entry, a blank line, and a non-JSON line
    transcript = load_recall_module("lib", "transcript.py")
    f = tmp_path / "t.jsonl"
    good = _user("valid")
    f.write_text(
        json.dumps(good) + "\n" + "\n" + "not json\n" + '["array not dict"]\n',
        encoding="utf-8",
    )

    # When reading
    result = transcript.read_entries(str(f))

    # Then only the valid dict entry is returned
    assert result == [good]
