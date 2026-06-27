"""Where a project's memory lives: stable key derivation, XDG roots, and IO.

The per-project directory name is the project ROOT path (resolved so every
worktree and branch of a repo share one store), dash-encoded. Durable memory
lives under $XDG_DATA_HOME; ephemeral state (locks, the transcript pointer,
logs) under $XDG_STATE_HOME, keyed by a short hash so it never collides yet
stays out of the human-readable data dir.

`Store` bundles the resolved key and both roots and exposes the path accessors
and small fail-open IO helpers, so the rest of the package never threads
`data_dir`/`state_dir`/`key` through every call.
"""

from __future__ import annotations

import contextlib
import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

PLUGIN_NS = "natelandau-recall"
LEARNINGS_DIRNAME = "learnings"
BACKLOG_NAME = "backlog.md"
HANDOFF_NAME = "HANDOFF.md"
LOCK_NAME = "sweep.lock"
TRANSCRIPT_POINTER_NAME = "transcript-path"
LOG_NAME = "sweep.log"
PROCESSED_NAME = "processed-sessions"
BOOTSTRAP_DIRNAME = "bootstrap"

_GIT_TIMEOUT = 5


def encode_project_key(path: Path) -> str:
    """Encode an absolute path into one flat directory name.

    The leading slash is dropped, then each remaining `/` becomes `-`; a path
    segment that begins with `.` (a hidden directory) has its leading dot turned
    into a dash, yielding a double dash at that boundary. Interior dots are kept.

    Dropping the leading slash (rather than encoding it to a leading `-`) keeps
    the key from starting with a dash, which shells and CLI tools would otherwise
    parse as an option flag (e.g. `rm -rf -Users-...`).
    """
    parts = [part for part in str(path).split("/") if part]
    encoded = ["-" + part[1:] if part.startswith(".") else part for part in parts]
    return "-".join(encoded)


def project_root(*, cwd: Path, env: Mapping[str, str]) -> Path:
    """Resolve the stable project root for `cwd`.

    Order: the git common dir's parent (shared across all worktrees/branches),
    else `CLAUDE_PROJECT_DIR`, else `cwd`. Always returns a resolved absolute
    path. Never raises -- git failures fall through to the env/cwd fallbacks.
    """
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],  # noqa: S607
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
            check=False,
            env=dict(env),
        )
        out = proc.stdout.strip()
        if proc.returncode == 0 and out:
            common = Path(out)
            return (common.parent if common.name == ".git" else common).resolve()
    except OSError, subprocess.SubprocessError:
        pass
    configured = env.get("CLAUDE_PROJECT_DIR")
    if configured:
        return Path(configured).resolve()
    return cwd.resolve()


def _xdg_root(env: Mapping[str, str], var: str, default_rel: str) -> Path:
    """Resolve an XDG base dir from `var`, falling back to ~/`default_rel`."""
    base = env.get(var)
    root = Path(base) if base else Path.home() / default_rel
    return root / PLUGIN_NS


def _data_dir(key: str, *, env: Mapping[str, str]) -> Path:
    """Return the durable memory dir for a project key (not created here)."""
    return _xdg_root(env, "XDG_DATA_HOME", ".local/share") / key


def _state_dir(key: str, *, env: Mapping[str, str]) -> Path:
    """Return the ephemeral state dir for a project key (hashed, not created)."""
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]  # noqa: S324
    return _xdg_root(env, "XDG_STATE_HOME", ".local/state") / digest


@dataclass(frozen=True, slots=True)
class Store:
    """The resolved memory location for one project: key + durable/ephemeral roots."""

    key: str
    data_dir: Path
    state_dir: Path

    @classmethod
    def for_cwd(cls, *, cwd: Path, env: Mapping[str, str]) -> Store:
        """Resolve the store for `cwd`: project root -> key -> XDG data/state dirs."""
        key = encode_project_key(project_root(cwd=cwd, env=env))
        return cls(key=key, data_dir=_data_dir(key, env=env), state_dir=_state_dir(key, env=env))

    @property
    def learnings_dir(self) -> Path:
        """Directory holding the atomic learning files."""
        return self.data_dir / LEARNINGS_DIRNAME

    @property
    def backlog_path(self) -> Path:
        """The deferred-work backlog file."""
        return self.data_dir / BACKLOG_NAME

    @property
    def handoff_path(self) -> Path:
        """The consume-once session handoff file (human-readable, beside the backlog)."""
        return self.data_dir / HANDOFF_NAME

    @property
    def lock_path(self) -> Path:
        """The single-writer sweep lock."""
        return self.state_dir / LOCK_NAME

    @property
    def transcript_pointer_path(self) -> Path:
        """The saved transcript path so the sweep finds it after /clear."""
        return self.state_dir / TRANSCRIPT_POINTER_NAME

    @property
    def log_path(self) -> Path:
        """The append-only sweep activity log."""
        return self.state_dir / LOG_NAME

    @property
    def processed_path(self) -> Path:
        """The ledger of session IDs already mined (by the live sweep or bootstrap)."""
        return self.state_dir / PROCESSED_NAME

    @property
    def bootstrap_dir(self) -> Path:
        """Scratch dir holding parsed past transcripts staged for the bootstrap."""
        return self.state_dir / BOOTSTRAP_DIRNAME

    def read_processed(self) -> set[str]:
        """Return the set of already-processed session IDs; empty when none/unreadable."""
        try:
            text = self.processed_path.read_text(encoding="utf-8")
        except OSError:
            return set()
        return {line.strip() for line in text.splitlines() if line.strip()}

    def add_processed(self, session_id: str) -> None:
        """Append a session ID to the ledger if absent; best-effort, never raises.

        Idempotent: a re-add of an existing ID is a no-op, so the live sweep can
        safely record the same session on each run without growing duplicates.
        """
        if not session_id or session_id in self.read_processed():
            return
        try:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            with self.processed_path.open("a", encoding="utf-8") as fh:
                fh.write(f"{session_id}\n")
        except OSError:
            pass

    def save_transcript_pointer(self, transcript_path: str) -> None:
        """Best-effort persist the transcript path for the sweep; never raises."""
        if not transcript_path:
            return
        try:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            self.transcript_pointer_path.write_text(transcript_path, encoding="utf-8")
        except OSError:
            pass

    def read_transcript_pointer(self) -> str:
        """Return the saved transcript path, or '' when none is stored."""
        try:
            return self.transcript_pointer_path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def read_handoff(self) -> str | None:
        """Return the consume-once handoff contents, or None when there is nothing to carry.

        Fails open: a missing, unreadable, empty, or non-UTF-8 HANDOFF.md (a
        hand-edited or pasted-in file) reads as None rather than raising, so one
        bad file never aborts the surrounding session-start injection.
        """
        try:
            text = self.handoff_path.read_text(encoding="utf-8")
        except OSError, UnicodeDecodeError:
            return None
        return text or None

    def delete_handoff(self) -> None:
        """Best-effort remove the handoff after it has been injected; never raises.

        Called only once the inject is emitted, so a delete the OS rejects leaves
        the baton in place for the next attempt rather than dropping it silently.
        """
        with contextlib.suppress(OSError):
            self.handoff_path.unlink()

    def is_empty(self) -> bool:
        """Return whether the store holds no backlog or learnings."""
        if self.backlog_path.exists():
            return False
        learnings = self.learnings_dir
        with contextlib.suppress(OSError):
            return not (learnings.is_dir() and any(learnings.glob("*.md")))
        return True
