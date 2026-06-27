"""Verify the sweep gate: lock acquisition, stale-lock stealing, exchange threshold, and run_job."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path
    from types import ModuleType

    import pytest


@dataclass(frozen=True)
class _Cfg:
    """Minimal Config stand-in for sweep tests."""

    profile: str = "standard"
    disabled_hooks: frozenset[str] = frozenset()
    project_dir: str | None = None
    hook_options: dict[str, dict[str, str]] = field(default_factory=dict)
    min_exchanges: int = 5

    def option(self, hook_id: str, key: str, default: str) -> str:
        """Return a per-hook string option or the default."""
        return default

    def int_option(self, hook_id: str, key: str, default: int) -> int:
        """Return min_exchanges when queried for sweep, else default."""
        if hook_id == "sweep" and key == "min_exchanges":
            return self.min_exchanges
        return default


# ---------------------------------------------------------------------------
# JSONL transcript helpers (mirror the shape produced by Claude Code)
# ---------------------------------------------------------------------------


def _user(text: str) -> dict:
    """Build a user entry with a plain-string content field."""
    return {"type": "user", "message": {"role": "user", "content": text}}


def _assistant(text: str) -> dict:
    """Build an assistant entry with a single text block."""
    return {
        "type": "assistant",
        "message": {
            "id": "msg_a",
            "role": "assistant",
            "content": [{"type": "text", "text": text}],
        },
    }


def _write_transcript(path: Path, entries: list[dict]) -> None:
    """Write a JSONL transcript file at the given path."""
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")


def _meaningful_entries(n: int) -> list[dict]:
    """Build n interleaved user/assistant entries, all meaningful (no noise)."""
    entries: list[dict] = []
    for i in range(n):
        if i % 2 == 0:
            entries.append(_user(f"User message {i}"))
        else:
            entries.append(_assistant(f"Assistant response {i}"))
    return entries


# ---------------------------------------------------------------------------
# acquire_lock tests
# ---------------------------------------------------------------------------


def test_acquire_lock_succeeds_on_first_call(
    tmp_path: Path,
    import_recall_module: Callable[[str], ModuleType],
) -> None:
    """Verify acquire_lock returns a lock path when the lock does not yet exist."""
    # Given an empty state dir and a fresh timestamp
    sweep = import_recall_module("lib.sweep")
    state_dir = tmp_path / "state"
    now = 1000.0

    # When acquiring the lock for the first time
    lock = sweep.acquire_lock(state_dir, now=now)

    # Then a path is returned, the file exists, and stores the timestamp
    assert lock is not None
    assert lock.exists()
    assert float(lock.read_text(encoding="utf-8").strip()) == now


def test_acquire_lock_second_call_returns_none_held(
    tmp_path: Path,
    import_recall_module: Callable[[str], ModuleType],
) -> None:
    """Verify a second acquire_lock with the same timestamp returns None (lock held)."""
    # Given an already-acquired fresh lock
    sweep = import_recall_module("lib.sweep")
    state_dir = tmp_path / "state"
    now = 1000.0
    first = sweep.acquire_lock(state_dir, now=now)
    assert first is not None

    # When acquiring again with the same now (well within stale_after)
    second = sweep.acquire_lock(state_dir, now=now)

    # Then the second attempt fails because the lock is still fresh
    assert second is None


def test_acquire_lock_steals_stale_lock(
    tmp_path: Path,
    import_recall_module: Callable[[str], ModuleType],
) -> None:
    """Verify a lock older than stale_after is stolen on a subsequent acquire."""
    # Given a lock acquired at now=1000 with a 300s stale window
    sweep = import_recall_module("lib.sweep")
    state_dir = tmp_path / "state"
    first = sweep.acquire_lock(state_dir, now=1000.0, stale_after=300.0)
    assert first is not None

    # When acquiring 400s later (past the 300s threshold)
    second = sweep.acquire_lock(state_dir, now=1400.0, stale_after=300.0)

    # Then the stale lock is stolen and a new lock is returned with the new timestamp
    assert second is not None
    assert float(second.read_text(encoding="utf-8").strip()) == 1400.0


def test_acquire_lock_steals_malformed_lock(
    tmp_path: Path,
    import_recall_module: Callable[[str], ModuleType],
) -> None:
    """Verify a lock with a non-numeric timestamp is treated as stale and stolen."""
    # Given an existing lock file with corrupt (non-float) content
    sweep = import_recall_module("lib.sweep")
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "sweep.lock").write_text("not-a-float", encoding="utf-8")

    # When acquiring (corrupt content parses to stored=0.0, so always stale)
    lock = sweep.acquire_lock(state_dir, now=400.0, stale_after=300.0)

    # Then the corrupt lock is stolen and the new timestamp is written
    assert lock is not None
    assert float(lock.read_text(encoding="utf-8").strip()) == 400.0


def test_acquire_lock_fresh_lock_not_stolen(
    tmp_path: Path,
    import_recall_module: Callable[[str], ModuleType],
) -> None:
    """Verify a lock within stale_after is not stolen."""
    # Given a lock acquired at now=1000 with a 300s stale window
    sweep = import_recall_module("lib.sweep")
    state_dir = tmp_path / "state"
    first = sweep.acquire_lock(state_dir, now=1000.0, stale_after=300.0)
    assert first is not None

    # When acquiring 200s later (within the 300s stale window)
    second = sweep.acquire_lock(state_dir, now=1200.0, stale_after=300.0)

    # Then the fresh lock is not stolen and None is returned
    assert second is None


# ---------------------------------------------------------------------------
# gate tests
# ---------------------------------------------------------------------------


def test_gate_returns_none_and_releases_lock_below_threshold(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    import_recall_module: Callable[[str], ModuleType],
) -> None:
    """Verify gate returns None and releases the lock when below min_exchanges."""
    # Given a project with a sparse transcript (2 entries) and a threshold of 5
    proj = tmp_path / "proj"
    proj.mkdir()
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj))

    t_file = tmp_path / "sparse.jsonl"
    _write_transcript(t_file, [_user("hello"), _assistant("hi")])

    sweep = import_recall_module("lib.sweep")
    store = import_recall_module("lib.store")
    env = dict(os.environ)
    key = store.project_key(cwd=proj, env=env)
    state_dir_path = store.state_dir(key, env=env)

    event: dict = {"cwd": str(proj), "transcript_path": str(t_file)}
    cfg = _Cfg(min_exchanges=5)

    # When gate is called with only 2 meaningful messages (< 5 threshold)
    result = sweep.gate(event, cfg, now=1000.0)

    # Then None is returned and the lock file is cleaned up
    assert result is None
    assert not (state_dir_path / "sweep.lock").exists()


def test_gate_returns_sweep_job_above_threshold(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    import_recall_module: Callable[[str], ModuleType],
) -> None:
    """Verify gate returns a SweepJob with the windowed entries when >= min_exchanges."""
    # Given a project with a rich transcript (6 meaningful entries, threshold=5)
    proj = tmp_path / "proj"
    proj.mkdir()
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj))

    entries = _meaningful_entries(6)
    t_file = tmp_path / "rich.jsonl"
    _write_transcript(t_file, entries)

    sweep = import_recall_module("lib.sweep")
    event: dict = {"cwd": str(proj), "transcript_path": str(t_file)}
    cfg = _Cfg(min_exchanges=5)

    # When gate is called with 6 meaningful messages (>= 5 threshold)
    result = sweep.gate(event, cfg, now=1000.0)

    # Then a SweepJob is returned, the lock stays held, and the window covers all entries
    assert result is not None
    assert result.transcript_path == str(t_file)
    assert len(result.window) == len(entries)
    # Lock is held on success (not released — the run step owns release)
    assert (result.state_dir / "sweep.lock").exists()


def test_gate_falls_back_to_transcript_pointer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    import_recall_module: Callable[[str], ModuleType],
) -> None:
    """Verify gate reads the transcript path from the state-dir pointer when event path is empty."""
    # Given a project whose state dir has a saved transcript-path pointer
    proj = tmp_path / "proj"
    proj.mkdir()
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj))

    entries = _meaningful_entries(6)
    t_file = tmp_path / "session.jsonl"
    _write_transcript(t_file, entries)

    # Compute the expected state_dir and write the transcript-path pointer into it
    sweep = import_recall_module("lib.sweep")
    store = import_recall_module("lib.store")
    env = dict(os.environ)
    key = store.project_key(cwd=proj, env=env)
    state_dir_path = store.state_dir(key, env=env)
    state_dir_path.mkdir(parents=True, exist_ok=True)
    (state_dir_path / "transcript-path").write_text(str(t_file), encoding="utf-8")

    # When gate is called with an empty transcript_path in the event
    event: dict = {"cwd": str(proj), "transcript_path": ""}
    cfg = _Cfg(min_exchanges=5)
    result = sweep.gate(event, cfg, now=1000.0)

    # Then a SweepJob is returned, using the path from the saved pointer
    assert result is not None
    assert result.transcript_path == str(t_file)
    assert len(result.window) == len(entries)


# ---------------------------------------------------------------------------
# validate_writes tests
# ---------------------------------------------------------------------------


def test_validate_writes_outside_data_dir_is_removed(
    tmp_path: Path,
    import_recall_module: Callable[[str], ModuleType],
) -> None:
    """Verify a changed file outside data_dir is deleted and noted as escaped."""
    # Given a file that lives outside data_dir
    sweep = import_recall_module("lib.sweep")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("should not be here", encoding="utf-8")

    # When validate_writes is called with that path
    notes = sweep.validate_writes([str(outside)], data_dir=data_dir)

    # Then the file is gone and a note is recorded
    assert not outside.exists()
    assert len(notes) == 1
    assert notes[0].startswith("escaped:")


def test_validate_writes_aws_key_redacted(
    tmp_path: Path,
    import_recall_module: Callable[[str], ModuleType],
) -> None:
    """Verify an AWS access key ID inside data_dir is redacted in place."""
    # Given a file inside data_dir containing an AKIA token
    sweep = import_recall_module("lib.sweep")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    target = data_dir / "memory.md"
    secret = "AKIAIOSFODNN7EXAMPLE"  # noqa: S105 - intentional fake credential for pattern testing
    target.write_text(f"key: {secret}", encoding="utf-8")

    # When validate_writes processes it
    notes = sweep.validate_writes([str(target)], data_dir=data_dir)

    # Then the secret is gone, the redaction marker is present, and the note is correct
    content = target.read_text(encoding="utf-8")
    assert secret not in content
    assert "«redacted-secret»" in content
    assert notes == [f"secret-redacted: {target}"]


def test_validate_writes_github_token_redacted(
    tmp_path: Path,
    import_recall_module: Callable[[str], ModuleType],
) -> None:
    """Verify a GitHub personal access token inside data_dir is redacted in place."""
    # Given a file inside data_dir containing a ghp_ token (30+ chars after prefix)
    sweep = import_recall_module("lib.sweep")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    target = data_dir / "notes.md"
    secret = "ghp_" + "A" * 30
    target.write_text(f"token={secret}", encoding="utf-8")

    # When validate_writes processes it
    notes = sweep.validate_writes([str(target)], data_dir=data_dir)

    # Then the secret is gone and the marker is present
    content = target.read_text(encoding="utf-8")
    assert secret not in content
    assert "«redacted-secret»" in content
    assert notes == [f"secret-redacted: {target}"]


def test_validate_writes_pem_private_key_redacted(
    tmp_path: Path,
    import_recall_module: Callable[[str], ModuleType],
) -> None:
    """Verify a PEM private key header inside data_dir is redacted in place."""
    # Given a file inside data_dir containing a PEM private-key header
    sweep = import_recall_module("lib.sweep")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    target = data_dir / "keys.md"
    # Constructed at runtime to avoid triggering the detect-private-key pre-commit hook
    secret = "-----BEGIN RSA " + "PRIVATE KEY-----"
    target.write_text(f"cert: {secret}", encoding="utf-8")

    # When validate_writes processes it
    notes = sweep.validate_writes([str(target)], data_dir=data_dir)

    # Then the header is gone and the marker is present
    content = target.read_text(encoding="utf-8")
    assert secret not in content
    assert "«redacted-secret»" in content
    assert notes == [f"secret-redacted: {target}"]


def test_validate_writes_api_key_value_redacted_label_preserved(
    tmp_path: Path,
    import_recall_module: Callable[[str], ModuleType],
) -> None:
    """Verify the api_key label is kept and only the value is redacted."""
    # Given a file inside data_dir with an api_key = <value> line
    sweep = import_recall_module("lib.sweep")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    target = data_dir / "config.md"
    value = "supersecretvalue12345"  # 21 chars, matches [A-Za-z0-9/+_-]{20,}
    target.write_text(f"api_key = {value}", encoding="utf-8")

    # When validate_writes processes it
    notes = sweep.validate_writes([str(target)], data_dir=data_dir)

    # Then the value is redacted but the label remains
    content = target.read_text(encoding="utf-8")
    assert value not in content
    assert "api_key" in content
    assert "«redacted-secret»" in content
    assert notes == [f"secret-redacted: {target}"]


def test_validate_writes_clean_file_untouched(
    tmp_path: Path,
    import_recall_module: Callable[[str], ModuleType],
) -> None:
    """Verify a clean file inside data_dir is left byte-identical and produces no note."""
    # Given a clean file inside data_dir with no secret content
    sweep = import_recall_module("lib.sweep")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    target = data_dir / "clean.md"
    original = "This is a normal memory file with nothing sensitive."
    target.write_text(original, encoding="utf-8")

    # When validate_writes processes it
    notes = sweep.validate_writes([str(target)], data_dir=data_dir)

    # Then the file is untouched and no notes are produced
    assert target.read_text(encoding="utf-8") == original
    assert notes == []


def test_validate_writes_missing_file_inside_data_dir_produces_no_note(
    tmp_path: Path,
    import_recall_module: Callable[[str], ModuleType],
) -> None:
    """Verify a path inside data_dir that doesn't exist on disk produces no note and doesn't raise."""
    # Given a path inside data_dir that was never written to disk
    sweep = import_recall_module("lib.sweep")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    ghost = data_dir / "ghost.md"

    # When validate_writes processes it
    notes = sweep.validate_writes([str(ghost)], data_dir=data_dir)

    # Then no note is produced and no exception is raised
    assert notes == []


# ---------------------------------------------------------------------------
# run_job tests (fake runner — never spawns real claude)
# ---------------------------------------------------------------------------


def _make_stream_json(file_path: str) -> str:
    """Build canned stream-json output reporting a single Write tool call."""
    assistant_line = json.dumps(
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "name": "Write",
                        "input": {"file_path": file_path, "content": "clean memory content"},
                    }
                ]
            },
        }
    )
    result_line = json.dumps({"type": "result", "result": "done"})
    return assistant_line + "\n" + result_line + "\n"


def _fake_runner_for(file_path: str) -> Callable[..., dict[str, object]]:
    """Return a fake runner that reports a Write to file_path and ignores all args."""

    def _runner(
        prompt: str,
        *,
        args: list[str],
        env: dict[str, str],
        cwd: str,
        timeout: int = 180,
    ) -> dict[str, object]:
        return {
            "success": True,
            "exit_code": 0,
            "stdout": _make_stream_json(file_path),
            "stderr": "",
        }

    return _runner


def test_run_job_clean_write_releases_lock_and_logs(
    tmp_path: Path,
    import_recall_module: Callable[[str], ModuleType],
) -> None:
    """Verify run_job parses written files, skips clean ones, writes sweep.log, and releases lock."""
    # Given a SweepJob with a pre-created file inside data_dir and a pre-created lock
    sweep = import_recall_module("lib.sweep")
    data_dir = tmp_path / "data"
    state_dir = tmp_path / "state"
    data_dir.mkdir(parents=True)
    state_dir.mkdir(parents=True)

    target = data_dir / "memory.md"
    target.write_text("clean memory content", encoding="utf-8")
    lock = state_dir / "sweep.lock"
    lock.write_text("12345.0", encoding="utf-8")

    job = sweep.SweepJob(
        data_dir=data_dir,
        state_dir=state_dir,
        transcript_path="",
        cwd=str(tmp_path),
        window=[],
    )
    cfg = _Cfg()
    fake = _fake_runner_for(str(target))

    # When run_job is called with the fake runner
    notes = sweep.run_job(job, cfg, runner=fake)

    # Then validate_writes ran (clean file → no notes), sweep.log exists, and lock is gone
    assert notes == []
    assert (state_dir / "sweep.log").exists()
    assert not lock.exists()


def test_run_job_escaped_write_removes_file_and_returns_note(
    tmp_path: Path,
    import_recall_module: Callable[[str], ModuleType],
) -> None:
    """Verify run_job removes a file written outside data_dir and returns an escaped note."""
    # Given a file pre-created OUTSIDE data_dir and a fake runner reporting it as written
    sweep = import_recall_module("lib.sweep")
    data_dir = tmp_path / "data"
    state_dir = tmp_path / "state"
    data_dir.mkdir(parents=True)
    state_dir.mkdir(parents=True)

    outside = tmp_path / "outside.md"
    outside.write_text("should not be here", encoding="utf-8")
    lock = state_dir / "sweep.lock"
    lock.write_text("12345.0", encoding="utf-8")

    job = sweep.SweepJob(
        data_dir=data_dir,
        state_dir=state_dir,
        transcript_path="",
        cwd=str(tmp_path),
        window=[],
    )
    cfg = _Cfg()
    fake = _fake_runner_for(str(outside))

    # When run_job is called with the fake runner
    notes = sweep.run_job(job, cfg, runner=fake)

    # Then the escaped file is gone, the note is recorded, and the lock is released
    assert not outside.exists()
    assert len(notes) == 1
    assert notes[0].startswith("escaped:")
    assert not lock.exists()


def test_run_job_always_releases_lock_on_runner_failure(
    tmp_path: Path,
    import_recall_module: Callable[[str], ModuleType],
) -> None:
    """Verify run_job releases the lock even when the runner raises an exception."""
    # Given a fake runner that always raises
    sweep = import_recall_module("lib.sweep")
    data_dir = tmp_path / "data"
    state_dir = tmp_path / "state"
    data_dir.mkdir(parents=True)
    state_dir.mkdir(parents=True)

    lock = state_dir / "sweep.lock"
    lock.write_text("12345.0", encoding="utf-8")

    job = sweep.SweepJob(
        data_dir=data_dir,
        state_dir=state_dir,
        transcript_path="",
        cwd=str(tmp_path),
        window=[],
    )
    cfg = _Cfg()

    def _exploding_runner(**_: object) -> dict[str, object]:
        msg = "simulated runner failure"
        raise RuntimeError(msg)

    # When run_job is called with the exploding runner
    notes = sweep.run_job(job, cfg, runner=_exploding_runner)

    # Then it returns empty notes and the lock is still released
    assert notes == []
    assert not lock.exists()
