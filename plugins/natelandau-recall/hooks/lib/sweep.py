"""The end-of-session memory sweep (deterministic gate + later: run/detach).

The gate runs inline in the SessionEnd/PreCompact hook: it acquires a per-project
lock (both events can fire close together), resolves the transcript (event then
the saved pointer), windows it since the last compaction, drops system/hook
noise, and returns a SweepJob only when the session carried enough real exchanges
to be worth a sweep. The heavy agent run is added in a later task.
"""

from __future__ import annotations

import contextlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from lib import store, transcript

if TYPE_CHECKING:
    from lib.config import Config

LOCK_NAME = "sweep.lock"
STALE_AFTER = 300.0
DEFAULT_MIN_EXCHANGES = 5


@dataclass(slots=True)
class SweepJob:
    """A gated, ready-to-run sweep over one session's windowed transcript."""

    data_dir: Path
    state_dir: Path
    transcript_path: str
    window: list[dict[str, Any]]


def acquire_lock(state_dir: Path, *, now: float, stale_after: float = STALE_AFTER) -> Path | None:
    """Atomically claim the sweep lock, stealing one older than `stale_after`.

    Returns the lock path on success, or None when a fresh lock is already held.
    The lock file stores the acquisition timestamp so a crashed sweep's lock can
    be reclaimed. Never raises.
    """
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    lock = state_dir / LOCK_NAME
    fd = _try_create(lock)
    if fd is None:
        try:
            stored = float(lock.read_text(encoding="utf-8").strip())
        except OSError, ValueError:
            stored = 0.0
        if now - stored <= stale_after:
            return None  # held and fresh
        try:
            lock.unlink()
        except OSError:
            return None
        fd = _try_create(lock)
        if fd is None:
            return None
    try:
        try:
            os.write(fd, str(now).encode("utf-8"))
        finally:
            os.close(fd)
    except OSError:
        # Write failed (ENOSPC/EIO); the empty lock file reads as stale next attempt.
        return None
    return lock


def _try_create(lock: Path) -> int | None:
    """Open the lock with O_CREAT|O_EXCL; return the fd or None if it exists/fails."""
    try:
        return os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return None
    except OSError:
        return None


def release_lock(lock: Path) -> None:
    """Best-effort remove the sweep lock; never raises."""
    with contextlib.suppress(OSError):
        lock.unlink(missing_ok=True)


def _resolve_transcript(event: dict[str, Any], state_dir: Path) -> str:
    """Return the transcript path from the event, else the saved pointer, else ""."""
    path = event.get("transcript_path") or ""
    if path:
        return path
    try:
        return (state_dir / "transcript-path").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def gate(event: dict[str, Any], cfg: Config, *, now: float) -> SweepJob | None:
    """Acquire the lock and return a SweepJob, or None when not worth sweeping.

    Resolves the project store from the event cwd, locks, resolves+windows the
    transcript, and bails (releasing the lock) when fewer than `min_exchanges`
    meaningful messages remain. The lock stays held on success for the run step
    to release. Never raises.
    """
    cwd = Path(event.get("cwd") or Path.cwd())
    key = store.project_key(cwd=cwd, env=os.environ)
    data_dir = store.data_dir(key, env=os.environ)
    state_dir = store.state_dir(key, env=os.environ)

    lock = acquire_lock(state_dir, now=now)
    if lock is None:
        return None
    try:
        transcript_path = _resolve_transcript(event, state_dir)
        entries = transcript.read_entries(transcript_path) if transcript_path else []
        window = transcript.window_since_compact(entries)
        meaningful = transcript.meaningful_messages(window)

        min_exchanges = cfg.int_option("sweep", "min_exchanges", DEFAULT_MIN_EXCHANGES)
        if len(meaningful) < min_exchanges:
            release_lock(lock)
            return None
        return SweepJob(
            data_dir=data_dir, state_dir=state_dir, transcript_path=transcript_path, window=window
        )
    except Exception:  # noqa: BLE001 - gate must never raise or leak the lock
        release_lock(lock)
        return None
