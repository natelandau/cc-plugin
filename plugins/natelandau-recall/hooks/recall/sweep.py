"""The end-of-session memory sweep: gate, detach, run, and validate the agent's writes.

The gate runs inline in the SessionEnd/PreCompact hook: it acquires a per-project
single-writer lock (both events can fire close together), resolves the transcript
(event then the saved pointer), windows it since the last compaction, drops
system/hook noise, and yields a SweepJob only when the session carried enough real
exchanges. The heavy `claude -p` pass runs in a double-forked daemon that outlives
session teardown; its writes pass a path-containment + secret-scrub backstop before
they are trusted. Every boundary fails open so a sweep never wedges the session.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from recall import transcript
from recall.config import RecallConfig
from recall.paths import is_within_root
from recall.runner import ClaudeRunner
from recall.safety import scrub
from recall.store import Store, git_safe_env

if TYPE_CHECKING:
    from collections.abc import Mapping

    from recall.runner import Runner

STALE_AFTER = 300.0
PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "sweep.md"
CRITERIA_PATH = Path(__file__).resolve().parent.parent / "prompts" / "_capture-criteria.md"


@dataclass(slots=True)
class SweepJob:
    """A gated, ready-to-run sweep over one session's windowed transcript."""

    window: list[dict[str, Any]]
    cwd: str
    session_id: str


class Lock:
    """Atomic single-writer lock with stale recovery; every operation fails open."""

    def __init__(self, path: Path, *, stale_after: float = STALE_AFTER) -> None:
        self.path = path
        self.stale_after = stale_after

    def _try_create(self) -> int | None:
        """Open the lock with O_CREAT|O_EXCL; return the fd or None if it exists/fails."""
        try:
            return os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except OSError:
            return None

    def acquire(self, *, now: float) -> bool:
        """Atomically claim the lock, stealing one older than `stale_after`.

        Returns True on success. A malformed or empty stored timestamp reads as
        stale (0.0) and is stolen. An `os.write` failure leaves an empty lock file
        that reads as stale next attempt and returns False. Never raises.
        """
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            return False
        fd = self._try_create()
        if fd is None:
            try:
                stored = float(self.path.read_text(encoding="utf-8").strip())
            except OSError, ValueError:
                stored = 0.0
            if now - stored <= self.stale_after:
                return False  # held and fresh
            try:
                self.path.unlink()
            except OSError:
                return False
            fd = self._try_create()
            if fd is None:
                return False
        try:
            try:
                os.write(fd, str(now).encode("utf-8"))
            finally:
                os.close(fd)
        except OSError:
            return False
        return True

    def release(self) -> None:
        """Best-effort remove the lock; never raises."""
        with contextlib.suppress(OSError):
            self.path.unlink(missing_ok=True)


def _transcript_text(window: list[dict[str, Any]]) -> str:
    """Serialize the window's real conversation (role + text only) for the prompt.

    Only the human's messages and the agent's user-facing text are sent; the
    agent's thinking, its tool calls/results, and system/hook noise are dropped
    by `transcript.meaningful_text` since none of them are durable memory.
    """
    return json.dumps(transcript.meaningful_text(window), ensure_ascii=False)


def _git_context(cwd: str, *, timeout: int = 10) -> str:
    """Return recent commit subjects (project repo ground truth), or '' on failure."""
    try:
        proc = subprocess.run(
            ["git", "log", "--format=%h %s (%cr)", "-20"],  # noqa: S607
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            # Strip leaked git-location vars so `git log` reads the repo at `cwd`,
            # not whatever repo an ambient GIT_DIR names.
            env=git_safe_env(os.environ),
        )
    except OSError, subprocess.SubprocessError:
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _render_template(path: Path, **variables: str) -> str:
    """Read a template file and substitute {{name}} placeholders."""
    content = path.read_text(encoding="utf-8")
    for key, value in variables.items():
        content = content.replace("{{" + key + "}}", value)
    return content


class Sweep:
    """The boundary-capture pipeline: gate -> detach -> run -> validate."""

    def __init__(self, store: Store, config: RecallConfig, runner: Runner) -> None:
        self.store = store
        self.config = config
        self.runner = runner

    def trigger(self, event: dict[str, Any]) -> None:
        """Gate the sweep and, if worthwhile, spawn the detached worker. Never raises."""
        with contextlib.suppress(Exception):
            job = self._gate(event, now=time.time())
            if job is not None:
                self._spawn_detached(job)

    def _gate(self, event: dict[str, Any], *, now: float) -> SweepJob | None:
        """Acquire the lock and return a SweepJob, or None when not worth sweeping.

        Never raises and never leaks the lock: on any post-acquire failure or a
        below-threshold window it releases the lock and returns None. On success
        the lock stays held for `_run_job` to release.
        """
        lock = Lock(self.store.lock_path)
        if not lock.acquire(now=now):
            return None
        try:
            transcript_path = event.get("transcript_path") or self.store.read_transcript_pointer()
            entries = transcript.read_entries(transcript_path) if transcript_path else []
            window = transcript.window_since_compact(entries)
            meaningful = transcript.meaningful_messages(window)
            if len(meaningful) < self.config.min_exchanges:
                lock.release()
                return None
            session_id = Path(transcript_path).stem if transcript_path else ""
            return SweepJob(
                window=window,
                cwd=str(event.get("cwd") or Path.cwd()),
                session_id=session_id,
            )
        except Exception:  # noqa: BLE001 - gate must never raise or leak the lock
            lock.release()
            return None

    def _run_job(self, job: SweepJob) -> list[str]:
        """Build the prompt, run the agent, validate its writes, log, free the lock.

        ALWAYS releases the lock and never raises (it runs in a detached worker
        with no one to catch it). Returns the remediation notes.
        """
        lock = Lock(self.store.lock_path)
        try:
            self.store.data_dir.mkdir(parents=True, exist_ok=True)
            prompt = _render_template(
                PROMPT_PATH,
                transcript=_transcript_text(job.window),
                existing_memory=self._existing_memory(),
                git_context=_git_context(job.cwd),
                capture_criteria=CRITERIA_PATH.read_text(encoding="utf-8"),
            )
            result = self.runner.run(prompt, cwd=str(self.store.data_dir))
            notes = self._validate_writes(result.changed_files)
            self._log_run(changed=result.changed_files, notes=notes)
        except Exception:  # noqa: BLE001 - the detached worker must never raise
            return []
        else:
            if result.success:
                self.store.add_processed(
                    job.session_id
                )  # add_processed is OSError-guarded (fail-open), safe in a never-raises worker
            return notes
        finally:
            lock.release()

    def _validate_writes(self, changed_files: list[str]) -> list[str]:
        """Enforce path containment + secret scrub on files the agent wrote.

        For each changed path: if it is outside `data_dir` (the signature of a
        prompt-injection steering the skip-permissions agent), revert it and record
        `escaped`. Otherwise scan its content and, on a secret hit, redact in place
        and record `secret-redacted`. Never raises; IO errors are recorded, not raised.
        """
        notes: list[str] = []
        for raw in changed_files:
            path = Path(raw)
            if not is_within_root(path, self.store.data_dir):
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
            scrubbed, changed = scrub(content)
            if changed:
                try:
                    path.write_text(scrubbed, encoding="utf-8")
                except OSError as exc:
                    notes.append(f"secret-found-unredactable: {raw} ({exc})")
                else:
                    notes.append(f"secret-redacted: {raw}")
        return notes

    def _existing_memory(self, *, max_chars: int = 50_000) -> str:
        """Concatenate the current store files so the sweep agent can dedup/refine."""
        parts: list[str] = []
        with contextlib.suppress(OSError):
            backlog = self.store.backlog_path
            parts.append(f"# {backlog.name}\n{backlog.read_text(encoding='utf-8')}")
        learnings = self.store.learnings_dir
        if learnings.is_dir():
            for f in sorted(learnings.glob("*.md")):
                with contextlib.suppress(OSError):
                    parts.append(f"# learnings/{f.name}\n{f.read_text(encoding='utf-8')}")
        return "\n\n".join(parts)[:max_chars]

    def _log_run(self, *, changed: list[str], notes: list[str]) -> None:
        """Append one line recording what the sweep changed; best-effort."""
        try:
            self.store.state_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(UTC).isoformat()
            with self.store.log_path.open("a", encoding="utf-8") as fh:
                fh.write(f"{stamp} changed={changed} notes={notes}\n")
        except OSError:
            pass

    def _redirect_stdio(self) -> None:
        """Point the daemon's stdio at sweep.out so it never touches the hook's stdout."""
        try:
            self.store.state_dir.mkdir(parents=True, exist_ok=True)
            out = os.open(
                str(self.store.state_dir / "sweep.out"),
                os.O_WRONLY | os.O_CREAT | os.O_APPEND,
                0o600,
            )
            null = os.open(os.devnull, os.O_RDONLY)
            os.dup2(null, 0)
            os.dup2(out, 1)
            os.dup2(out, 2)
        except OSError:
            pass

    def _spawn_detached(self, job: SweepJob) -> None:
        """Daemonize the sweep so it outlives session teardown (validated by spike).

        Double-fork + setsid detaches the worker into its own session; the parent
        (the hook) reaps the intermediate child and returns immediately. The worker
        redirects stdio away from the hook's stdout BEFORE running the job. This is
        the one untested seam (it forks real processes); `_run_job` carries the
        logic and is tested via an injected fake runner.
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
        self._redirect_stdio()
        with contextlib.suppress(BaseException):
            self._run_job(job)
        os._exit(0)


def run_sweep(event: dict[str, Any], *, env: Mapping[str, str]) -> None:
    """Build the store/config/runner from the event and trigger the sweep. Never raises.

    The single wiring point both `sessionend.py` and `precompact.py` call, so the
    thin scripts don't duplicate construction.
    """
    cwd = Path(event.get("cwd") or Path.cwd())
    store = Store.for_cwd(cwd=cwd, env=env)
    config = RecallConfig.load(project_dir=env.get("CLAUDE_PROJECT_DIR"))
    runner = ClaudeRunner(model=config.sweep_model)
    Sweep(store, config, runner).trigger(event)
