"""Verify transcript reading, windowing, and noise filtering for the recall sweep."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from recall import transcript  # ty: ignore[unresolved-import]

if TYPE_CHECKING:
    from pathlib import Path


def _user(text: str) -> dict:
    """Build a user entry with a plain-string content field."""
    return {"type": "user", "message": {"role": "user", "content": text}}


def _assistant(text: str, msg_id: str = "msg_a") -> dict:
    """Build an assistant entry with a single text block."""
    return {
        "type": "assistant",
        "message": {"id": msg_id, "role": "assistant", "content": [{"type": "text", "text": text}]},
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
    """Build a compact-boundary entry using the given shape."""
    if boundary_type == "type":
        return {"type": "compact_boundary", "summary": "..."}
    if boundary_type == "flag":
        return {"type": "summary", "isCompactSummary": True}
    return {"type": "summary", "compact_boundary": True}


# ---------------------------------------------------------------------------
# window_since_compact
# ---------------------------------------------------------------------------


def test_window_drops_up_to_and_including_boundary() -> None:
    """Verify window excludes everything up to and including the boundary entry."""
    # Given entries with one compact boundary in the middle
    before = [_user("pre"), _assistant("pre reply")]
    after = [_user("post"), _assistant("post reply")]
    entries = [*before, _compact("type"), *after]
    # When windowing since the last compact boundary
    result = transcript.window_since_compact(entries)
    # Then only post-boundary entries are returned
    assert result == after


def test_window_uses_last_boundary() -> None:
    """Verify window uses the *last* compact boundary when multiple are present."""
    # Given two compact boundaries
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


def test_window_no_boundary_returns_all() -> None:
    """Verify all entries are returned when no compact boundary is present."""
    # Given entries with no compact boundary
    entries = [_user("hello"), _assistant("hi"), _user("bye")]
    # When windowing
    result = transcript.window_since_compact(entries)
    # Then all entries are returned unchanged
    assert result == entries


@pytest.mark.parametrize("btype", ["type", "flag", "field"])
def test_window_recognizes_all_boundary_shapes(btype: str) -> None:
    """Verify all three compact-boundary field shapes are recognized."""
    # Given a boundary of each shape with trailing content
    entries = [_user("before"), _compact(btype), _user("after")]
    # When windowing
    result = transcript.window_since_compact(entries)
    # Then only the post-boundary entry is returned
    assert len(result) == 1
    assert result[0]["message"]["content"] == "after"


# ---------------------------------------------------------------------------
# meaningful_messages
# ---------------------------------------------------------------------------


def test_meaningful_passes_normal_exchange() -> None:
    """Verify a normal user/assistant exchange is kept intact."""
    # Given a simple user + assistant turn
    entries = [_user("Can you help?"), _assistant("Sure.")]
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
def test_meaningful_filters_noise_markers(noise_text: str) -> None:
    """Verify entries whose text contains any NOISE_MARKER are excluded."""
    # Given a user entry with a noise marker in its text
    entries = [_user(noise_text)]
    # When filtering meaningful messages
    result = transcript.meaningful_messages(entries)
    # Then the noisy entry is excluded
    assert result == []


def test_meaningful_drops_tool_result_user() -> None:
    """Verify user entries whose content is a list (tool_result) are dropped."""
    # Given a tool-result user line / When filtering
    result = transcript.meaningful_messages([_tool_result_user()])
    # Then the tool-result entry is excluded (content is a list, not a string)
    assert result == []


def test_meaningful_drops_thinking_only_assistant() -> None:
    """Verify assistant entries with only a thinking block and no text are dropped."""
    # Given an assistant entry with a thinking block but no text block / When filtering
    result = transcript.meaningful_messages([_thinking_assistant()])
    # Then the pure-thinking entry is excluded
    assert result == []


def test_meaningful_mixed_noise_and_clean() -> None:
    """Verify noise entries are removed while clean entries are preserved."""
    # Given a mix of noisy and clean entries
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
# meaningful_text (prompt-ready role + text view)
# ---------------------------------------------------------------------------


def test_meaningful_text_keeps_only_user_and_agent_text() -> None:
    """Verify meaningful_text returns role+text for human and agent-visible messages only."""
    # Given a window mixing a user message and a rich assistant turn
    user = _user("How do I do X?")
    assistant = {
        "type": "assistant",
        "message": {
            "content": [
                {"type": "thinking", "thinking": "PRIVATE reasoning"},
                {"type": "text", "text": "Do it like this."},
                {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}},
            ]
        },
    }
    entries = [
        user,
        assistant,
        _tool_result_user(),
        _user("<system-reminder>noise</system-reminder>"),
    ]

    # When extracting the prompt-ready view
    out = transcript.meaningful_text(entries)

    # Then only the human text and the agent's user-facing text survive
    assert out == [
        {"role": "user", "text": "How do I do X?"},
        {"role": "assistant", "text": "Do it like this."},
    ]


def test_meaningful_text_empty_window_returns_empty() -> None:
    """Verify a window with no real messages yields an empty list."""
    # Given only tool noise and a thinking-only turn / When extracting
    out = transcript.meaningful_text([_tool_result_user(), _thinking_assistant()])
    # Then nothing is produced
    assert out == []


# ---------------------------------------------------------------------------
# read_entries
# ---------------------------------------------------------------------------


def test_read_entries_parses_jsonl(tmp_path: Path) -> None:
    """Verify read_entries parses a well-formed JSONL file into a list of dicts."""
    # Given a JSONL file with two entries
    f = tmp_path / "t.jsonl"
    e1, e2 = _user("hello"), _assistant("world")
    f.write_text(json.dumps(e1) + "\n" + json.dumps(e2) + "\n", encoding="utf-8")
    # When reading
    result = transcript.read_entries(str(f))
    # Then both entries are returned
    assert result == [e1, e2]


def test_read_entries_missing_file_returns_empty(tmp_path: Path) -> None:
    """Verify read_entries returns [] rather than raising when the file is absent."""
    # Given a path that does not exist / When reading
    result = transcript.read_entries(str(tmp_path / "nope.jsonl"))
    # Then an empty list is returned (fail-open)
    assert result == []


def test_read_entries_skips_blank_and_invalid_lines(tmp_path: Path) -> None:
    """Verify malformed or blank JSONL lines are skipped without error."""
    # Given a file with a valid entry, a blank line, a non-JSON line, and a JSON array
    f = tmp_path / "t.jsonl"
    good = _user("valid")
    f.write_text(json.dumps(good) + "\n\nnot json\n" + '["array not dict"]\n', encoding="utf-8")
    # When reading
    result = transcript.read_entries(str(f))
    # Then only the valid dict entry is returned
    assert result == [good]
