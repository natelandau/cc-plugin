"""The end-of-session memory sweep (deterministic gate + later: run/detach).

The gate runs inline in the SessionEnd/PreCompact hook: it acquires a per-project
lock (both events can fire close together), resolves the transcript (event then
the saved pointer), windows it since the last compaction, drops system/hook
noise, and returns a SweepJob only when the session carried enough real exchanges
to be worth a sweep. The heavy agent run is added in a later task.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from lib import claude_runner, store, transcript
from lib.paths import is_within_root

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
    cwd: str
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
            data_dir=data_dir,
            state_dir=state_dir,
            transcript_path=transcript_path,
            cwd=str(cwd),
            window=window,
        )
    except Exception:  # noqa: BLE001 - gate must never raise or leak the lock
        release_lock(lock)
        return None


# ---------------------------------------------------------------------------
# Post-sweep validation: path containment + secret scrub
# ---------------------------------------------------------------------------

_REDACTED = "«redacted-secret»"

# (pattern, replacement). Token-shaped secrets replace the whole match; the
# key:value form preserves the label and redacts only the value.
SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"AKIA[0-9A-Z]{16}"), _REDACTED),
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"), _REDACTED),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), _REDACTED),
    (
        re.compile(
            r"(?i)((?:api[_-]?key|secret|token|password)\s*[:=]\s*['\"]?)([A-Za-z0-9/+_\-]{20,})"
        ),
        r"\1" + _REDACTED,
    ),
)


def _scrub(text: str) -> tuple[str, bool]:
    """Redact any secret-shaped content; return (scrubbed_text, changed)."""
    changed = False
    for pattern, repl in SECRET_PATTERNS:
        text, n = pattern.subn(repl, text)
        if n:
            changed = True
    return text, changed


PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "sweep.md"
DEFAULT_MODEL = "claude-sonnet-4-6"
RUN_TIMEOUT = claude_runner.DEFAULT_TIMEOUT


def _transcript_text(window: list[dict[str, Any]]) -> str:
    """Serialize the user/assistant entries of the window for the prompt."""
    relevant = [e for e in window if e.get("type") in {"user", "assistant"}]
    return json.dumps(relevant, ensure_ascii=False)


def _existing_memory(data_dir: Path, *, max_chars: int = 50_000) -> str:
    """Concatenate the current store files so the sweep agent can dedup/refine."""
    parts: list[str] = []
    for name in (store.ARCHITECTURE_NAME, store.BACKLOG_NAME):
        with contextlib.suppress(OSError):
            parts.append(f"# {name}\n{(data_dir / name).read_text(encoding='utf-8')}")
    learnings = data_dir / store.LEARNINGS_DIRNAME
    if learnings.is_dir():
        for f in sorted(learnings.glob("*.md")):
            with contextlib.suppress(OSError):
                parts.append(f"# learnings/{f.name}\n{f.read_text(encoding='utf-8')}")
    return "\n\n".join(parts)[:max_chars]


def _git_context(cwd: str, *, timeout: int = 10) -> str:
    """Return recent commit subjects as ground truth, or '' on any failure."""
    try:
        proc = subprocess.run(
            ["git", "log", "--format=%h %s (%cr)", "-20"],  # noqa: S607
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except OSError, subprocess.SubprocessError:
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _log_run(state_dir: Path, *, changed: list[str], notes: list[str]) -> None:
    """Append one line recording what the sweep changed; best-effort."""
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).isoformat()
        with (state_dir / "sweep.log").open("a", encoding="utf-8") as fh:
            fh.write(f"{stamp} changed={changed} notes={notes}\n")
    except OSError:
        pass


def run_job(job: SweepJob, cfg: Config, *, runner: Any = claude_runner.run) -> list[str]:
    """Run the headless sweep for a gated job, validate its writes, free the lock.

    Builds the prompt from the template, invokes `runner` (real `claude -p` by
    default; tests inject a fake), enforces path-containment + secret scrub on the
    files the agent wrote, logs the outcome, and ALWAYS releases the lock. Returns
    the remediation notes. Never raises (it runs in a detached worker with no one
    to catch it).
    """
    lock = job.state_dir / LOCK_NAME
    try:
        job.data_dir.mkdir(parents=True, exist_ok=True)
        prompt = claude_runner.load_template(
            PROMPT_PATH,
            transcript=_transcript_text(job.window),
            existing_memory=_existing_memory(job.data_dir),
            git_context=_git_context(job.cwd),
        )
        args = claude_runner.build_args(model=cfg.option("sweep", "model", DEFAULT_MODEL))
        env = claude_runner.build_env(base=os.environ)
        result = runner(prompt, args=args, env=env, cwd=str(job.data_dir), timeout=RUN_TIMEOUT)
        tools, _ = claude_runner.parse_stream_json(str(result.get("stdout", "")))
        changed = [t["file"] for t in tools if "file" in t]
        notes = validate_writes(changed, data_dir=job.data_dir)
        _log_run(job.state_dir, changed=changed, notes=notes)
    except Exception:  # noqa: BLE001 - the detached worker must never raise
        return []
    else:
        return notes
    finally:
        release_lock(lock)


def _redirect_stdio(state_dir: Path) -> None:
    """Point the daemon's stdio at sweep.out so it never touches the hook's stdout."""
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        out = os.open(str(state_dir / "sweep.out"), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        null = os.open(os.devnull, os.O_RDONLY)
        os.dup2(null, 0)
        os.dup2(out, 1)
        os.dup2(out, 2)
    except OSError:
        pass


def _spawn_detached(job: SweepJob, cfg: Config) -> None:
    """Daemonize the sweep so it outlives session teardown (validated by spike).

    Double-fork + setsid detaches the worker into its own session; the parent
    (the hook) reaps the intermediate child and returns immediately. The worker
    redirects stdio away from the hook's stdout, runs the job, and exits. This is
    the one untested seam (it forks real processes); run_job carries the logic and
    is tested via an injected fake runner.
    """
    try:
        pid = os.fork()
    except OSError:
        return  # cannot fork; skip the sweep rather than block the hook
    if pid > 0:
        with contextlib.suppress(OSError):
            os.waitpid(pid, 0)  # reap the intermediate child (grandchild reparents to init)
        return
    # intermediate child
    try:
        os.setsid()
        pid2 = os.fork()
    except OSError:
        os._exit(0)
    if pid2 > 0:
        os._exit(0)
    # grandchild = the daemon
    _redirect_stdio(job.state_dir)
    with contextlib.suppress(BaseException):
        run_job(job, cfg)
    os._exit(0)


def trigger(event: dict[str, Any], cfg: Config) -> None:
    """Gate the sweep and, if worthwhile, spawn the detached worker. Never raises."""
    with contextlib.suppress(Exception):
        job = gate(event, cfg, now=time.time())
        if job is not None:
            _spawn_detached(job, cfg)


def validate_writes(changed_files: list[str], *, data_dir: Path) -> list[str]:
    """Enforce path containment + secret scrub on files the sweep agent wrote.

    For each changed path: if it is outside `data_dir` (the signature of a
    prompt-injection steering the skip-permissions agent), revert it and record
    `escaped`. Otherwise scan its content and, on a secret hit, redact in place
    and record `secret-redacted`. Never raises; IO errors are recorded, not raised.

    Args:
        changed_files: File paths reported as written by the sweep agent.
        data_dir: The trusted directory all sweep writes must stay within.

    Returns:
        List of remediation notes, one per file that required intervention.
    """
    notes: list[str] = []
    for raw in changed_files:
        path = Path(raw)
        if not is_within_root(path, data_dir):
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                notes.append(f"escaped-unremovable: {raw} ({exc})")
            else:
                notes.append(f"escaped: {raw}")
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue  # absent/unreadable: nothing to scan
        scrubbed, changed = _scrub(content)
        if changed:
            try:
                path.write_text(scrubbed, encoding="utf-8")
            except OSError as exc:
                notes.append(f"secret-found-unredactable: {raw} ({exc})")
            else:
                notes.append(f"secret-redacted: {raw}")
    return notes
