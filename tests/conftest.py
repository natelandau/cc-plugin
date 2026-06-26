"""Shared pytest fixtures for hook tests."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping


# Strip GIT_* vars so subprocess git commands don't inherit state from a parent
# pre-commit run (GIT_INDEX_FILE, GIT_DIR, etc. would point the ephemeral repo
# at the outer repo's index and break tree-building).
_CLEAN_GIT_ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


@pytest.fixture(scope="session")
def repos(tmp_path_factory: pytest.TempPathFactory) -> Mapping[str, str]:
    """Provide two ephemeral git repos (master, feat) plus a non-repo dir.

    Session-scoped because the hooks under test never write to the working tree.
    Recreating per test would slow the suite without changing behavior.
    """
    root = tmp_path_factory.mktemp("repos")
    master = root / "master_repo"
    feat = root / "feat_repo"
    for path, branch in ((master, "master"), (feat, "feat")):
        path.mkdir()
        subprocess.run(
            ["git", "init", "-q", "-b", branch, str(path)],
            check=True,
            capture_output=True,
            env=_CLEAN_GIT_ENV,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(path),
                "-c",
                "user.email=test@example.com",
                "-c",
                "user.name=test",
                "commit",
                "--allow-empty",
                "-q",
                "-m",
                "init",
            ],
            check=True,
            capture_output=True,
            env=_CLEAN_GIT_ENV,
        )
        # Neutralize the runner's global/XDG excludesfile so `git check-ignore`
        # (used by the gitignored-path bypass) sees only this repo's .gitignore.
        # Without this, a developer's global ignore of e.g. *.log would leak in
        # and make the gitignore-driven cases pass or fail per machine.
        subprocess.run(
            ["git", "-C", str(path), "config", "core.excludesFile", "/dev/null"],
            check=True,
            capture_output=True,
            env=_CLEAN_GIT_ENV,
        )
    # A .gitignore in the master repo lets branch-protection tests exercise
    # the gitignored-file bypass. check-ignore reads the working-tree file,
    # so it need not be committed. Patterns chosen to not collide with the
    # foo.py / foo.ipynb paths other cases use.
    (master / ".gitignore").write_text("*.ignored\nignored_dir/\n", encoding="utf-8")
    outside = root / "outside"
    outside.mkdir()
    return {"master": str(master), "feat": str(feat), "outside": str(outside)}


@pytest.fixture(scope="session")
def hooks_dir() -> Path:
    """Resolve the plugin's hooks directory."""
    return Path(__file__).resolve().parent.parent / "plugins" / "natelandau-toolkit" / "hooks"


@pytest.fixture
def run_pretooluse(
    hooks_dir: Path, tmp_path: Path
) -> Callable[[dict[str, Any]], subprocess.CompletedProcess[str]]:
    """Return a callable that pipes a payload through the PreToolUse dispatcher.

    Shared by every suite that drives the full dispatcher (protect_secrets,
    protect_system, use_uv, enforce_commit_message). Runs the subprocess in an
    isolated non-git directory and clears CLAUDE_PROJECT_DIR so neither the host
    repo's branch nor a developer's project config can perturb the rule under
    test: `enforce_branch_protection` resolves the branch from the process cwd,
    so running inside the repo on `main` would otherwise block every
    file-modifying payload before the rule being exercised is reached.
    """
    hook = hooks_dir / "pretooluse.py"

    def _run(payload: dict[str, Any]) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        env.pop("CLAUDE_PROJECT_DIR", None)
        # Point the session-keyed state bridge at a per-test tmp dir so hooks
        # that debounce via lib.state never read/write the shared system temp
        # bridge, keeping the subprocess suite isolated and rerunnable.
        env["NATELANDAU_TOOLKIT_STATE_DIR"] = str(tmp_path / "state")
        return subprocess.run(
            [str(hook)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            cwd=str(tmp_path),
            env=env,
        )

    return _run
