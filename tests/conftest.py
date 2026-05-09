"""Shared pytest fixtures for hook tests."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Mapping


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
        )
    outside = root / "outside"
    outside.mkdir()
    return {"master": str(master), "feat": str(feat), "outside": str(outside)}


@pytest.fixture(scope="session")
def hooks_dir() -> Path:
    """Resolve the plugin's hooks directory."""
    return Path(__file__).resolve().parent.parent / "hooks"
