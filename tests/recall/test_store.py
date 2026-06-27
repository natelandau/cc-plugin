"""Verify project-key derivation, XDG roots, and the Store path/IO helpers."""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

from recall.store import Store, encode_project_key, project_root  # ty: ignore[unresolved-import]

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


# ---------------------------------------------------------------------------
# encode_project_key
# ---------------------------------------------------------------------------


def test_encode_plain_path() -> None:
    """Verify a normal absolute path dash-encodes with a leading dash."""
    # Given a non-hidden absolute path / When encoded
    out = encode_project_key(Path("/Users/nate/repos/cc-plugin"))
    # Then slashes become dashes and the leading slash is a leading dash
    assert out == "-Users-nate-repos-cc-plugin"


def test_encode_hidden_segment_double_dash() -> None:
    """Verify a leading-dot segment yields a double dash."""
    # Given a path containing a hidden directory / When encoded
    out = encode_project_key(Path("/Users/nate/.local/share/chezmoi/dotfiles"))
    # Then the /.local boundary becomes a double dash; interior dots are preserved
    assert out == "-Users-nate--local-share-chezmoi-dotfiles"


def test_encode_interior_dot_preserved() -> None:
    """Verify a dot inside a segment is not doubled."""
    # Given a path with an interior dot / When encoded
    out = encode_project_key(Path("/srv/my.project/src"))
    # Then only the segment-leading dot rule applies (none here)
    assert out == "-srv-my.project-src"


# ---------------------------------------------------------------------------
# project_root
# ---------------------------------------------------------------------------


def test_project_root_git_common_dir(tmp_path: Path) -> None:
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
    root = project_root(cwd=wt, env=_CLEAN)

    # Then it is the MAIN worktree root, not the worktree dir
    assert root == main.resolve()


def test_project_root_non_git_uses_claude_project_dir(tmp_path: Path) -> None:
    """Verify a non-git dir falls back to CLAUDE_PROJECT_DIR."""
    # Given a non-git working dir and CLAUDE_PROJECT_DIR set to a project root
    proj = tmp_path / "proj"
    proj.mkdir()
    sub = proj / "sub"
    sub.mkdir()
    env = {**_CLEAN, "CLAUDE_PROJECT_DIR": str(proj)}

    # When resolving from a subdirectory
    root = project_root(cwd=sub, env=env)

    # Then the configured project root wins over raw cwd
    assert root == proj.resolve()


# ---------------------------------------------------------------------------
# Store.for_cwd: XDG roots and key hashing
# ---------------------------------------------------------------------------


def test_for_cwd_data_dir_honors_xdg(tmp_path: Path) -> None:
    """Verify the data dir nests the key under $XDG_DATA_HOME/natelandau-recall."""
    # Given a non-git project and an explicit XDG_DATA_HOME
    proj = tmp_path / "proj"
    proj.mkdir()
    env = {**_CLEAN, "CLAUDE_PROJECT_DIR": str(proj), "XDG_DATA_HOME": str(tmp_path / "xdg")}

    # When building the store for that cwd
    store = Store.for_cwd(cwd=proj, env=env)

    # Then the data dir is rooted under the plugin namespace at the encoded key
    assert store.data_dir == tmp_path / "xdg" / "natelandau-recall" / store.key
    assert store.key == encode_project_key(proj.resolve())


def test_for_cwd_state_dir_hashes_key(tmp_path: Path) -> None:
    """Verify the state dir nests a 12-char sha1 of the key under $XDG_STATE_HOME."""
    # Given a non-git project and an explicit XDG_STATE_HOME
    proj = tmp_path / "proj"
    proj.mkdir()
    env = {**_CLEAN, "CLAUDE_PROJECT_DIR": str(proj), "XDG_STATE_HOME": str(tmp_path / "st")}

    # When building the store
    store = Store.for_cwd(cwd=proj, env=env)

    # Then the state dir is hashed (not the raw key) under the plugin namespace
    expected_hash = hashlib.sha1(store.key.encode("utf-8")).hexdigest()[:12]  # noqa: S324
    assert store.state_dir == tmp_path / "st" / "natelandau-recall" / expected_hash


# ---------------------------------------------------------------------------
# Store path accessors + IO helpers
# ---------------------------------------------------------------------------


def _store_at(tmp_path: Path) -> Store:
    return Store(key="k", data_dir=tmp_path / "data", state_dir=tmp_path / "state")


def test_path_accessors(tmp_path: Path) -> None:
    """Verify the path properties point at the expected store locations."""
    # Given a store rooted at tmp dirs
    store = _store_at(tmp_path)
    # Then each accessor composes the right path
    assert store.learnings_dir == tmp_path / "data" / "learnings"
    assert store.backlog_path == tmp_path / "data" / "backlog.md"
    assert store.architecture_path == tmp_path / "data" / "architecture.md"
    assert store.lock_path == tmp_path / "state" / "sweep.lock"
    assert store.transcript_pointer_path == tmp_path / "state" / "transcript-path"
    assert store.log_path == tmp_path / "state" / "sweep.log"


def test_save_and_read_transcript_pointer(tmp_path: Path) -> None:
    """Verify the transcript pointer round-trips through the state dir."""
    # Given a store with no state dir yet
    store = _store_at(tmp_path)
    # When saving a transcript path
    store.save_transcript_pointer("/tmp/x/t.jsonl")  # noqa: S108
    # Then it is read back verbatim (mkdir handled internally)
    assert store.read_transcript_pointer() == "/tmp/x/t.jsonl"  # noqa: S108


def test_read_transcript_pointer_missing_returns_empty(tmp_path: Path) -> None:
    """Verify reading an absent pointer returns '' rather than raising."""
    # Given a store whose pointer was never written
    store = _store_at(tmp_path)
    # Then reading fails open to an empty string
    assert store.read_transcript_pointer() == ""


def test_save_transcript_pointer_ignores_empty(tmp_path: Path) -> None:
    """Verify saving an empty transcript path writes nothing."""
    # Given a store
    store = _store_at(tmp_path)
    # When saving an empty path
    store.save_transcript_pointer("")
    # Then no pointer file is created
    assert not store.transcript_pointer_path.exists()


def test_is_empty_true_when_no_artifacts(tmp_path: Path) -> None:
    """Verify is_empty reports True when no memory artifacts exist."""
    # Given a store with an empty (absent) data dir
    store = _store_at(tmp_path)
    # Then the store is empty
    assert store.is_empty() is True


def test_is_empty_false_with_a_learning(tmp_path: Path) -> None:
    """Verify is_empty reports False once a learning file exists."""
    # Given a store whose learnings dir holds one file
    store = _store_at(tmp_path)
    store.learnings_dir.mkdir(parents=True)
    (store.learnings_dir / "x.md").write_text("body", encoding="utf-8")
    # Then the store is not empty
    assert store.is_empty() is False
