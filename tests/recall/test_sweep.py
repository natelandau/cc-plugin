"""Verify the sweep: lock lifecycle, gate threshold, write validation, and run_job."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from recall.config import RecallConfig  # ty: ignore[unresolved-import]
from recall.runner import RunResult  # ty: ignore[unresolved-import]
from recall.store import Store  # ty: ignore[unresolved-import]
from recall.sweep import Lock, Sweep, SweepJob  # ty: ignore[unresolved-import]

if TYPE_CHECKING:
    from pathlib import Path


def _store(tmp_path: Path) -> Store:
    return Store(key="k", data_dir=tmp_path / "data", state_dir=tmp_path / "state")


class _FakeRunner:
    """Duck-typed Runner that reports a canned set of changed files; never spawns claude."""

    def __init__(self, changed_files: list[str]) -> None:
        self.changed_files = changed_files

    def run(self, prompt: str, *, cwd: str) -> RunResult:
        return RunResult(
            success=True,
            exit_code=0,
            changed_files=list(self.changed_files),
            text="done",
            stderr="",
        )


# ---------------------------------------------------------------------------
# Lock
# ---------------------------------------------------------------------------


def test_lock_acquire_succeeds_first(tmp_path: Path) -> None:
    """Verify acquire returns True and writes the timestamp when the lock is free."""
    # Given a lock path under a not-yet-created dir
    lock = Lock(tmp_path / "state" / "sweep.lock")
    # When acquiring for the first time
    assert lock.acquire(now=1000.0) is True
    # Then the file exists and stores the timestamp
    assert float(lock.path.read_text(encoding="utf-8").strip()) == 1000.0


def test_lock_held_second_acquire_fails(tmp_path: Path) -> None:
    """Verify a second acquire within the stale window returns False."""
    # Given an already-held fresh lock
    lock = Lock(tmp_path / "state" / "sweep.lock")
    assert lock.acquire(now=1000.0) is True
    # When acquiring again well within the stale window
    second = Lock(tmp_path / "state" / "sweep.lock")
    # Then it fails (the lock is still fresh)
    assert second.acquire(now=1100.0) is False


def test_lock_steals_stale(tmp_path: Path) -> None:
    """Verify a lock older than stale_after is stolen and re-stamped."""
    # Given a lock acquired at t=1000 with a 300s window
    Lock(tmp_path / "state" / "sweep.lock").acquire(now=1000.0)
    # When acquiring 400s later (past the threshold)
    stealer = Lock(tmp_path / "state" / "sweep.lock", stale_after=300.0)
    # Then the stale lock is stolen and the new timestamp written
    assert stealer.acquire(now=1400.0) is True
    assert float(stealer.path.read_text(encoding="utf-8").strip()) == 1400.0


def test_lock_steals_malformed(tmp_path: Path) -> None:
    """Verify a lock with a non-numeric timestamp is treated as stale and stolen."""
    # Given an existing lock file with corrupt content
    lock = Lock(tmp_path / "state" / "sweep.lock")
    lock.path.parent.mkdir(parents=True)
    lock.path.write_text("not-a-float", encoding="utf-8")
    # When acquiring (corrupt parses to stored=0.0, always stale)
    assert lock.acquire(now=400.0) is True


def test_lock_release_removes_file(tmp_path: Path) -> None:
    """Verify release unlinks the lock file and never raises when already gone."""
    # Given a held lock
    lock = Lock(tmp_path / "state" / "sweep.lock")
    lock.acquire(now=1.0)
    # When released twice
    lock.release()
    lock.release()
    # Then the file is gone and no error was raised
    assert not lock.path.exists()


# ---------------------------------------------------------------------------
# Sweep._gate
# ---------------------------------------------------------------------------


def _user(text: str) -> dict:
    return {"type": "user", "message": {"role": "user", "content": text}}


def _assistant(text: str) -> dict:
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}


def _meaningful(n: int) -> list[dict]:
    return [_user(f"u{i}") if i % 2 == 0 else _assistant(f"a{i}") for i in range(n)]


def _write_transcript(path: Path, entries: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")


def test_gate_below_threshold_returns_none_and_releases(tmp_path: Path) -> None:
    """Verify gate returns None and releases the lock below min_exchanges."""
    # Given a sparse transcript (2 meaningful) and a threshold of 5
    store = _store(tmp_path)
    t_file = tmp_path / "sparse.jsonl"
    _write_transcript(t_file, [_user("hi"), _assistant("yo")])
    sweep = Sweep(store, RecallConfig(min_exchanges=5), _FakeRunner([]))
    event = {"cwd": str(tmp_path), "transcript_path": str(t_file)}
    # When gating
    result = sweep._gate(event, now=1000.0)
    # Then None is returned and the lock is cleaned up
    assert result is None
    assert not store.lock_path.exists()


def test_gate_above_threshold_returns_job_and_holds_lock(tmp_path: Path) -> None:
    """Verify gate returns a SweepJob with the window and keeps the lock held."""
    # Given a rich transcript (6 meaningful, threshold 5)
    store = _store(tmp_path)
    entries = _meaningful(6)
    t_file = tmp_path / "rich.jsonl"
    _write_transcript(t_file, entries)
    sweep = Sweep(store, RecallConfig(min_exchanges=5), _FakeRunner([]))
    event = {"cwd": str(tmp_path / "proj"), "transcript_path": str(t_file)}
    # When gating
    result = sweep._gate(event, now=1000.0)
    # Then a job covering all entries is returned and the lock stays held for run_job
    assert result is not None
    assert result.cwd == str(tmp_path / "proj")
    assert len(result.window) == len(entries)
    assert store.lock_path.exists()


def test_gate_falls_back_to_transcript_pointer(tmp_path: Path) -> None:
    """Verify gate reads the saved pointer when the event transcript path is empty."""
    # Given a store with a saved transcript pointer
    store = _store(tmp_path)
    entries = _meaningful(6)
    t_file = tmp_path / "session.jsonl"
    _write_transcript(t_file, entries)
    store.save_transcript_pointer(str(t_file))
    sweep = Sweep(store, RecallConfig(min_exchanges=5), _FakeRunner([]))
    # When gating with an empty event transcript path
    result = sweep._gate({"cwd": str(tmp_path), "transcript_path": ""}, now=1000.0)
    # Then the job is built from the pointer's transcript
    assert result is not None
    assert len(result.window) == len(entries)


# ---------------------------------------------------------------------------
# Sweep._validate_writes (containment + secret scrub)
# ---------------------------------------------------------------------------


def _sweep_with_data(tmp_path: Path) -> tuple[Sweep, Path]:
    store = _store(tmp_path)
    store.data_dir.mkdir(parents=True)
    return Sweep(store, RecallConfig(), _FakeRunner([])), store.data_dir


def test_validate_writes_escaped_file_removed(tmp_path: Path) -> None:
    """Verify a changed file outside data_dir is deleted and noted as escaped."""
    # Given a file outside data_dir
    sweep, _ = _sweep_with_data(tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text("nope", encoding="utf-8")
    # When validating
    notes = sweep._validate_writes([str(outside)])
    # Then the file is gone and an escaped note is recorded
    assert not outside.exists()
    assert notes == [f"escaped: {outside}"]


def test_validate_writes_aws_key_redacted(tmp_path: Path) -> None:
    """Verify an AWS access key ID inside data_dir is redacted in place."""
    # Given a file containing an AKIA token
    sweep, data_dir = _sweep_with_data(tmp_path)
    target = data_dir / "m.md"
    secret = "AKIAIOSFODNN7EXAMPLE"  # noqa: S105 - fake credential for pattern testing
    target.write_text(f"key: {secret}", encoding="utf-8")
    # When validating
    notes = sweep._validate_writes([str(target)])
    # Then the secret is redacted and noted
    assert secret not in target.read_text(encoding="utf-8")
    assert "«redacted-secret»" in target.read_text(encoding="utf-8")
    assert notes == [f"secret-redacted: {target}"]


def test_validate_writes_github_token_redacted(tmp_path: Path) -> None:
    """Verify a GitHub personal access token inside data_dir is redacted."""
    # Given a file containing a ghp_ token
    sweep, data_dir = _sweep_with_data(tmp_path)
    target = data_dir / "n.md"
    secret = "ghp_" + "A" * 30
    target.write_text(f"token={secret}", encoding="utf-8")
    # When validating / Then it is redacted
    notes = sweep._validate_writes([str(target)])
    assert secret not in target.read_text(encoding="utf-8")
    assert notes == [f"secret-redacted: {target}"]


def test_validate_writes_pem_key_redacted(tmp_path: Path) -> None:
    """Verify a PEM private-key header inside data_dir is redacted."""
    # Given a file containing a PEM header (built at runtime to dodge secret scanners)
    sweep, data_dir = _sweep_with_data(tmp_path)
    target = data_dir / "k.md"
    secret = "-----BEGIN RSA " + "PRIVATE KEY-----"
    target.write_text(f"cert: {secret}", encoding="utf-8")
    # When validating / Then it is redacted
    notes = sweep._validate_writes([str(target)])
    assert secret not in target.read_text(encoding="utf-8")
    assert notes == [f"secret-redacted: {target}"]


def test_validate_writes_api_key_value_redacted_label_kept(tmp_path: Path) -> None:
    """Verify the api_key label is kept and only the value is redacted."""
    # Given an api_key = <value> line
    sweep, data_dir = _sweep_with_data(tmp_path)
    target = data_dir / "c.md"
    value = "supersecretvalue12345"  # 21 chars, matches the value pattern
    target.write_text(f"api_key = {value}", encoding="utf-8")
    # When validating
    notes = sweep._validate_writes([str(target)])
    content = target.read_text(encoding="utf-8")
    # Then the value is gone but the label survives
    assert value not in content
    assert "api_key" in content
    assert notes == [f"secret-redacted: {target}"]


def test_validate_writes_clean_file_untouched(tmp_path: Path) -> None:
    """Verify a clean file inside data_dir is left byte-identical with no note."""
    # Given a clean file
    sweep, data_dir = _sweep_with_data(tmp_path)
    target = data_dir / "clean.md"
    original = "nothing sensitive here."
    target.write_text(original, encoding="utf-8")
    # When validating / Then it is untouched
    notes = sweep._validate_writes([str(target)])
    assert target.read_text(encoding="utf-8") == original
    assert notes == []


def test_validate_writes_missing_file_no_note(tmp_path: Path) -> None:
    """Verify a path inside data_dir that was never written produces no note."""
    # Given a ghost path inside data_dir
    sweep, data_dir = _sweep_with_data(tmp_path)
    # When validating / Then nothing is noted and nothing raises
    assert sweep._validate_writes([str(data_dir / "ghost.md")]) == []


# ---------------------------------------------------------------------------
# Sweep._run_job (fake runner — never spawns real claude)
# ---------------------------------------------------------------------------


def _job_store(tmp_path: Path) -> Store:
    store = _store(tmp_path)
    store.data_dir.mkdir(parents=True)
    store.state_dir.mkdir(parents=True)
    store.lock_path.write_text("12345.0", encoding="utf-8")  # pre-held lock
    return store


def test_run_job_clean_write_logs_and_releases_lock(tmp_path: Path) -> None:
    """Verify run_job validates writes, logs, and releases the lock on a clean run."""
    # Given a store with a clean target file and a pre-held lock
    store = _job_store(tmp_path)
    target = store.data_dir / "memory.md"
    target.write_text("clean memory content", encoding="utf-8")
    sweep = Sweep(store, RecallConfig(), _FakeRunner([str(target)]))
    job = SweepJob(window=[], cwd=str(tmp_path))
    # When running the job
    notes = sweep._run_job(job)
    # Then the clean file yields no notes, the log is written, and the lock is freed
    assert notes == []
    assert store.log_path.exists()
    assert not store.lock_path.exists()


def test_run_job_escaped_write_reverted_and_lock_released(tmp_path: Path) -> None:
    """Verify run_job reverts a write outside data_dir and still releases the lock."""
    # Given a runner that reports a file written outside data_dir
    store = _job_store(tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text("nope", encoding="utf-8")
    sweep = Sweep(store, RecallConfig(), _FakeRunner([str(outside)]))
    job = SweepJob(window=[], cwd=str(tmp_path))
    # When running the job
    notes = sweep._run_job(job)
    # Then the escaped file is gone, noted, and the lock is released
    assert not outside.exists()
    assert notes == [f"escaped: {outside}"]
    assert not store.lock_path.exists()


def test_run_job_releases_lock_on_runner_failure(tmp_path: Path) -> None:
    """Verify run_job releases the lock even when the runner raises."""
    # Given a runner that always raises

    class _Exploding:
        def run(self, prompt: str, *, cwd: str) -> RunResult:
            msg = "boom"
            raise RuntimeError(msg)

    store = _job_store(tmp_path)
    sweep = Sweep(store, RecallConfig(), _Exploding())
    job = SweepJob(window=[], cwd=str(tmp_path))
    # When running the job
    notes = sweep._run_job(job)
    # Then it returns no notes and the lock is still released
    assert notes == []
    assert not store.lock_path.exists()
