"""Where a project's memory lives: stable key derivation and XDG roots.

The per-project directory name is the project ROOT path (resolved so every
worktree and branch of a repo share one store), dash-encoded. Durable memory
lives under $XDG_DATA_HOME; ephemeral state (locks, the transcript pointer,
logs) under $XDG_STATE_HOME, keyed by a short hash so it never collides yet
stays out of the human-readable data dir. See spec §4.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

PLUGIN_NS = "natelandau-recall"
LEARNINGS_DIRNAME = "learnings"
BACKLOG_NAME = "backlog.md"
ARCHITECTURE_NAME = "architecture.md"

_GIT_TIMEOUT = 5


def encode_project_key(path: Path) -> str:
    """Encode an absolute path into one flat directory name.

    Each `/` becomes `-` (a leading `/` becomes a leading `-`); a path segment
    that begins with `.` (a hidden directory) has its leading dot turned into a
    dash too, yielding a double dash at that boundary. Interior dots are kept.
    Mirrors Claude Code's own project-dir convention.
    """
    parts = str(path).split("/")
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


def project_key(*, cwd: Path, env: Mapping[str, str]) -> str:
    """Return the encoded directory name for `cwd`'s project."""
    return encode_project_key(project_root(cwd=cwd, env=env))


def _xdg_root(env: Mapping[str, str], var: str, default_rel: str) -> Path:
    """Resolve an XDG base dir from `var`, falling back to ~/`default_rel`."""
    base = env.get(var)
    root = Path(base) if base else Path.home() / default_rel
    return root / PLUGIN_NS


def data_dir(key: str, *, env: Mapping[str, str]) -> Path:
    """Return the durable memory dir for a project key (not created here)."""
    return _xdg_root(env, "XDG_DATA_HOME", ".local/share") / key


def state_dir(key: str, *, env: Mapping[str, str]) -> Path:
    """Return the ephemeral state dir for a project key (hashed, not created)."""
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]  # noqa: S324
    return _xdg_root(env, "XDG_STATE_HOME", ".local/state") / digest
