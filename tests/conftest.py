"""Shared pytest fixtures for hook tests."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Mapping


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
    outside = root / "outside"
    outside.mkdir()
    return {"master": str(master), "feat": str(feat), "outside": str(outside)}


@pytest.fixture(scope="session")
def hooks_dir() -> Path:
    """Resolve the plugin's hooks directory."""
    return Path(__file__).resolve().parent.parent / "plugins" / "natelandau-toolkit" / "hooks"
