"""Unit tests for the bootstrap discovery/selection/apply engine."""

from __future__ import annotations

from pathlib import Path

from recall import bootstrap  # ty: ignore[unresolved-import]


def test_claude_project_dir_name_matches_claude_code_encoding() -> None:
    # Given paths with dots, spaces, and slashes
    # Then non [A-Za-z0-9-] chars (incl. the leading slash) become dashes
    assert (
        bootstrap.claude_project_dir_name(Path("/Users/x/repos/cc-plugin"))
        == "-Users-x-repos-cc-plugin"
    )
    assert bootstrap.claude_project_dir_name(Path("/Users/x/.claude")) == "-Users-x--claude"
    assert bootstrap.claude_project_dir_name(Path("/a/App Support/b")) == "-a-App-Support-b"


def test_transcripts_dir_for_builds_projects_path() -> None:
    # Given a home and a cwd
    home = Path("/home/u")
    # Then the transcript dir is ~/.claude/projects/<encoded>
    assert bootstrap.transcripts_dir_for(Path("/p/q"), home=home) == (
        home / ".claude" / "projects" / "-p-q"
    )


def test_list_transcripts_oldest_first(tmp_path: Path) -> None:
    # Given two transcripts with distinct mtimes
    old = tmp_path / "old.jsonl"
    new = tmp_path / "new.jsonl"
    old.write_text("{}\n", encoding="utf-8")
    new.write_text("{}\n", encoding="utf-8")
    import os

    os.utime(old, (1000, 1000))
    os.utime(new, (2000, 2000))
    # Then they come back oldest-first
    assert bootstrap.list_transcripts(tmp_path) == [old, new]


def test_list_transcripts_missing_dir_is_empty(tmp_path: Path) -> None:
    # Given a non-existent dir
    assert bootstrap.list_transcripts(tmp_path / "nope") == []


def test_is_sweep_transcript_detects_signature() -> None:
    # Given a parsed transcript whose first user message is the sweeper prompt
    parsed = [{"role": "user", "text": "You are the project-memory sweeper. Update..."}]
    assert bootstrap.is_sweep_transcript(parsed) is True
    # And a normal conversation is not flagged
    assert bootstrap.is_sweep_transcript([{"role": "user", "text": "fix the bug"}]) is False


def test_session_id_of_is_stem() -> None:
    assert bootstrap.session_id_of(Path("/x/abc-123.jsonl")) == "abc-123"
