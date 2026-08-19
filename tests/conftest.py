"""Shared pytest fixtures for hook tests."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from tests._env import clean_environ

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping


@pytest.fixture(scope="session", autouse=True)
def _strip_ambient_git_vars() -> Iterator[None]:
    """Remove inherited git-location and path-exemption vars for the whole run.

    A GIT_DIR or GIT_CONFIG_* exported by an outer git hook or worktree would
    otherwise retarget any git subprocess spawned with a bare os.environ.copy(),
    not just the calls that pass an explicit sanitized env. The toolkit's
    path-exemption variables go the same way, so the exemption they grant is
    only ever in play for the tests that set them themselves.
    """
    original = dict(os.environ)
    stripped_keys = set(original) - set(clean_environ())
    for key in stripped_keys:
        del os.environ[key]
    try:
        yield
    finally:
        for key in stripped_keys:
            os.environ[key] = original[key]


@pytest.fixture(scope="session")
def repos(tmp_path_factory: pytest.TempPathFactory) -> Mapping[str, str]:
    """Provide three ephemeral git repos (master, feat, exempt) plus a non-repo dir.

    `exempt` is a second repo on a protected branch, for tests that declare it
    an exempt root: keeping it distinct from `master` is what proves the
    carve-out is scoped to the exempt tree rather than to every protected repo.

    Session-scoped because the hooks under test never write to the working tree.
    Recreating per test would slow the suite without changing behavior.
    """
    root = tmp_path_factory.mktemp("repos")
    master = root / "master_repo"
    feat = root / "feat_repo"
    exempt = root / "exempt_repo"
    for path, branch in ((master, "master"), (feat, "feat"), (exempt, "master")):
        path.mkdir()
        subprocess.run(
            ["git", "init", "-q", "-b", branch, str(path)],
            check=True,
            capture_output=True,
            env=clean_environ(),
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
            env=clean_environ(),
        )
        # Neutralize the runner's global/XDG excludesfile so `git check-ignore`
        # (used by the gitignored-path bypass) sees only this repo's .gitignore.
        # Without this, a developer's global ignore of e.g. *.log would leak in
        # and make the gitignore-driven cases pass or fail per machine.
        subprocess.run(
            ["git", "-C", str(path), "config", "core.excludesFile", "/dev/null"],
            check=True,
            capture_output=True,
            env=clean_environ(),
        )
    # A .gitignore in the master repo lets branch-protection tests exercise
    # the gitignored-file bypass. check-ignore reads the working-tree file,
    # so it need not be committed. Patterns chosen to not collide with the
    # foo.py / foo.ipynb paths other cases use.
    (master / ".gitignore").write_text("*.ignored\nignored_dir/\n", encoding="utf-8")
    outside = root / "outside"
    outside.mkdir()
    return {
        "master": str(master),
        "feat": str(feat),
        "exempt": str(exempt),
        "outside": str(outside),
    }


@pytest.fixture(scope="session")
def empty_home(tmp_path_factory: pytest.TempPathFactory) -> str:
    """Provide a home directory holding no toolkit config.

    Hook subprocesses resolve `~/.claude/natelandau-toolkit.toml`, so without
    pointing HOME here a developer's own global config would decide the profile,
    the disabled hooks, and the exempt paths for every subprocess test.
    """
    return str(tmp_path_factory.mktemp("empty_home"))


@pytest.fixture(scope="session")
def hooks_dir() -> Path:
    """Resolve the plugin's hooks directory."""
    return Path(__file__).resolve().parent.parent / "plugins" / "natelandau-toolkit" / "hooks"


@pytest.fixture
def run_pretooluse(
    hooks_dir: Path, tmp_path: Path, empty_home: str
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
        env["HOME"] = empty_home
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
