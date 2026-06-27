"""Verify project-key derivation, encoding, and XDG roots."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import ModuleType

_CLEAN = {"PATH": os.environ.get("PATH", "")}

# Git env vars that refer to a specific repository location; must be cleared so
# test-spawned git commands target the tmp repo, not the outer checkout.
_GIT_REPO_VARS = frozenset(
    {
        "GIT_DIR",
        "GIT_COMMON_DIR",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_WORK_TREE",
    }
)

_GIT_ENV = {k: v for k, v in os.environ.items() if k not in _GIT_REPO_VARS}


def _git(path: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True, env=_GIT_ENV)


@pytest.fixture(scope="session")
def store(load_recall_module: Callable[..., ModuleType]) -> ModuleType:
    """Load the store module via the shared recall loader."""
    return load_recall_module("lib", "store.py")


def test_encode_plain_path(store: ModuleType) -> None:
    """Verify a normal absolute path dash-encodes with a leading dash."""
    # Given a non-hidden absolute path
    # When encoded
    out = store.encode_project_key(Path("/Users/nate/repos/cc-plugin"))
    # Then slashes become dashes and the leading slash is a leading dash
    assert out == "-Users-nate-repos-cc-plugin"


def test_encode_hidden_segment_double_dash(store: ModuleType) -> None:
    """Verify a leading-dot segment yields a double dash."""
    # Given a path containing a hidden directory
    # When encoded
    out = store.encode_project_key(Path("/Users/nate/.local/share/chezmoi/dotfiles"))
    # Then the /.local boundary becomes a double dash; interior dots are preserved
    assert out == "-Users-nate--local-share-chezmoi-dotfiles"


def test_encode_interior_dot_preserved(store: ModuleType) -> None:
    """Verify a dot inside a segment is not doubled."""
    # Given a path with an interior dot
    # When encoded
    out = store.encode_project_key(Path("/srv/my.project/src"))
    # Then only the segment-leading dot rule applies (none here)
    assert out == "-srv-my.project-src"


def test_project_root_git_common_dir(store: ModuleType, tmp_path: Path) -> None:
    """Verify all worktrees of a repo resolve to the main worktree root."""
    # Given a git repo with a linked worktree
    main = tmp_path / "main"
    main.mkdir()
    _git(main, "init", "-q")
    (main / "f").write_text("x")
    _git(main, "add", "f")
    _git(main, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init")
    wt = tmp_path / "wt"
    _git(main, "worktree", "add", "-q", str(wt))

    # When resolving the root from inside the worktree
    root = store.project_root(cwd=wt, env=_CLEAN)

    # Then it is the MAIN worktree root, not the worktree dir
    assert root == main.resolve()


def test_project_root_non_git_uses_claude_project_dir(store: ModuleType, tmp_path: Path) -> None:
    """Verify a non-git dir falls back to CLAUDE_PROJECT_DIR."""
    # Given a non-git working dir and CLAUDE_PROJECT_DIR set to a project root
    proj = tmp_path / "proj"
    proj.mkdir()
    sub = proj / "sub"
    sub.mkdir()
    env = {**_CLEAN, "CLAUDE_PROJECT_DIR": str(proj)}

    # When resolving from a subdirectory
    root = store.project_root(cwd=sub, env=env)

    # Then the configured project root wins over raw cwd
    assert root == proj.resolve()


def test_data_dir_honors_xdg(store: ModuleType, tmp_path: Path) -> None:
    """Verify data_dir nests the key under $XDG_DATA_HOME/natelandau-recall."""
    # Given an explicit XDG_DATA_HOME
    env = {**_CLEAN, "XDG_DATA_HOME": str(tmp_path / "xdg")}
    # When computing the data dir for a key
    d = store.data_dir("-Users-nate-repo", env=env)
    # Then it is rooted under the plugin namespace
    assert d == tmp_path / "xdg" / "natelandau-recall" / "-Users-nate-repo"
