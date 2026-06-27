"""Unit tests for the bootstrap discovery/selection/apply engine."""

from __future__ import annotations

import json
from pathlib import Path

from recall.config import RecallConfig  # ty: ignore[unresolved-import]

from recall import bootstrap  # ty: ignore[unresolved-import]
from tests.recall._store_factory import store_at


def _write_transcript(path: Path, *, exchanges: int, first_user: str = "hello") -> None:
    """Write a JSONL transcript with `exchanges` user+assistant text messages."""
    lines: list[str] = []
    for i in range(exchanges):
        role = "user" if i % 2 == 0 else "assistant"
        text = first_user if i == 0 else f"msg {i}"
        if role == "user":
            lines.append(json.dumps({"type": "user", "message": {"content": text}}))
        else:
            lines.append(
                json.dumps(
                    {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}
                )
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _bootstrap(tmp_path: Path, cwd: Path) -> bootstrap.Bootstrap:
    store = store_at(tmp_path)
    return bootstrap.Bootstrap(
        store=store, config=RecallConfig(min_exchanges=2), home=tmp_path / "home", cwd=cwd
    )


def _tdir(tmp_path: Path, cwd: Path) -> Path:
    d = bootstrap.transcripts_dir_for(cwd, home=tmp_path / "home")
    d.mkdir(parents=True, exist_ok=True)
    return d


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


def test_discover_stages_eligible_transcripts(tmp_path: Path) -> None:
    """Verify discover stages non-live eligible transcripts oldest-first."""
    # Given two healthy transcripts plus the live (newest) one
    cwd = Path("/proj")
    tdir = _tdir(tmp_path, cwd)
    _write_transcript(tdir / "old.jsonl", exchanges=4)
    _write_transcript(tdir / "mid.jsonl", exchanges=4)
    _write_transcript(tdir / "live.jsonl", exchanges=4)
    import os

    os.utime(tdir / "old.jsonl", (1000, 1000))
    os.utime(tdir / "mid.jsonl", (2000, 2000))
    os.utime(tdir / "live.jsonl", (3000, 3000))  # newest == live, auto-excluded

    # When discovering
    manifest = _bootstrap(tmp_path, cwd).discover(limit=None)

    # Then the live session is excluded and the rest are staged oldest-first
    ids = [e["session_id"] for e in manifest]
    assert ids == ["old", "mid"]
    for entry in manifest:
        assert Path(str(entry["scratch_path"])).is_file()


def test_discover_skips_short_sweep_and_processed(tmp_path: Path) -> None:
    """Verify discover filters out tiny, sweep, and already-processed sessions."""
    cwd = Path("/proj")
    tdir = _tdir(tmp_path, cwd)
    _write_transcript(tdir / "tiny.jsonl", exchanges=1)  # below min_exchanges=2
    _write_transcript(tdir / "sweep.jsonl", exchanges=4, first_user=bootstrap.SWEEP_SIGNATURE)
    _write_transcript(tdir / "done.jsonl", exchanges=4)
    _write_transcript(tdir / "keep.jsonl", exchanges=4)
    _write_transcript(tdir / "live.jsonl", exchanges=4)
    import os

    for i, name in enumerate(["tiny", "sweep", "done", "keep", "live"]):
        os.utime(tdir / f"{name}.jsonl", (1000 + i, 1000 + i))

    # When discovering with "done" already in the ledger
    bs = _bootstrap(tmp_path, cwd)
    bs.store.add_processed("done")

    # Then only "keep" survives all filters
    manifest = bs.discover(limit=None)
    assert [e["session_id"] for e in manifest] == ["keep"]


def test_discover_limit_keeps_most_recent(tmp_path: Path) -> None:
    """Verify that limit retains the most recent N candidates, returned oldest-first."""
    cwd = Path("/proj")
    tdir = _tdir(tmp_path, cwd)
    for i, name in enumerate(["a", "b", "c", "live"]):
        _write_transcript(tdir / f"{name}.jsonl", exchanges=4)
        import os

        os.utime(tdir / f"{name}.jsonl", (1000 + i, 1000 + i))

    # When limited to the 2 most recent (live excluded first)
    manifest = _bootstrap(tmp_path, cwd).discover(limit=2)
    # Then the two newest non-live sessions remain, oldest-first
    assert [e["session_id"] for e in manifest] == ["b", "c"]


def test_apply_writes_learnings_and_backlog_and_ledger(tmp_path: Path) -> None:
    """Verify apply writes learnings and backlog files and records session ids in the ledger."""
    # Given a bootstrap instance and a merge plan
    bs = _bootstrap(tmp_path, Path("/proj"))
    plan = {
        "learnings": [{"filename": "trap.md", "content": "summary: a trap\n"}],
        "backlog": "# backlog\n- [ ] [S] do a thing\n",
        "processed_session_ids": ["s1", "s2"],
    }
    # When apply is called
    result = bs.apply(plan)
    # Then files are written and ledger is updated
    assert (bs.store.learnings_dir / "trap.md").read_text(encoding="utf-8") == "summary: a trap\n"
    assert bs.store.backlog_path.read_text(encoding="utf-8").startswith("# backlog")
    assert bs.store.read_processed() == {"s1", "s2"}
    assert result["ledger_added"] == 2


def test_apply_rejects_path_escape(tmp_path: Path) -> None:
    """Verify apply rejects paths that escape the store and writes nothing outside it."""
    # Given a plan with a path-traversal filename
    bs = _bootstrap(tmp_path, Path("/proj"))
    plan = {
        "learnings": [{"filename": "../escape.md", "content": "x"}],
        "backlog": None,
        "processed_session_ids": [],
    }
    # When apply is called
    result = bs.apply(plan)
    # Then nothing is written outside the store and the op is reported rejected
    assert not (bs.store.data_dir.parent / "escape.md").exists()
    assert any("escape.md" in r for r in result["rejected"])


def test_apply_rejects_absolute_filename(tmp_path: Path) -> None:
    """Verify apply rejects a learning whose filename is an absolute path."""
    # Given a plan with an absolute path as the learning filename
    bs = _bootstrap(tmp_path, Path("/proj"))
    plan = {
        "learnings": [{"filename": "/etc/passwd", "content": "x"}],
        "backlog": None,
        "processed_session_ids": [],
    }
    # When apply is called
    result = bs.apply(plan)
    # Then the absolute path is reported rejected and nothing was written
    assert any("/etc/passwd" in r for r in result["rejected"])
    assert result["written"] == []


def test_apply_redacts_secrets(tmp_path: Path) -> None:
    """Verify apply scrubs secrets from content before writing and records the path."""
    # Given a plan whose learning content contains a secret-shaped token
    bs = _bootstrap(tmp_path, Path("/proj"))
    secret = "abcdefghijklmnopqrst" + "uvwxyz0123"
    plan = {
        "learnings": [{"filename": "leak.md", "content": f"token = '{secret}'"}],
        "backlog": None,
        "processed_session_ids": [],
    }
    # When apply is called
    bs.apply(plan)
    # Then the written file does not contain the secret
    written = (bs.store.learnings_dir / "leak.md").read_text(encoding="utf-8")
    assert secret not in written
