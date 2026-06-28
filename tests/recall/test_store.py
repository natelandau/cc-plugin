"""Verify project-key derivation, XDG roots, and the Store path/IO helpers."""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

from recall.store import Store, encode_project_key, project_root  # ty: ignore[unresolved-import]

from tests._env import clean_environ
from tests.recall._store_factory import store_at

_CLEAN = {"PATH": os.environ.get("PATH", "")}

# Strip the git location vars so test-spawned git commands target the tmp repo,
# not whatever checkout the suite runs from.
_GIT_ENV = clean_environ()


def _git(path: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True, env=_GIT_ENV)


# ---------------------------------------------------------------------------
# encode_project_key
# ---------------------------------------------------------------------------


def test_encode_plain_path() -> None:
    """Verify a normal absolute path dash-encodes without a leading dash."""
    # Given a non-hidden absolute path / When encoded
    out = encode_project_key(Path("/Users/nate/repos/cc-plugin"))
    # Then slashes become dashes and the leading slash is dropped (no flag-like dash)
    assert out == "Users-nate-repos-cc-plugin"
    assert not out.startswith("-")


def test_encode_hidden_segment_double_dash() -> None:
    """Verify an interior leading-dot segment yields a double dash."""
    # Given a path containing a hidden directory / When encoded
    out = encode_project_key(Path("/Users/nate/.local/share/chezmoi/dotfiles"))
    # Then the /.local boundary becomes a double dash; interior dots are preserved
    assert out == "Users-nate--local-share-chezmoi-dotfiles"


def test_encode_interior_dot_preserved() -> None:
    """Verify a dot inside a segment is not doubled."""
    # Given a path with an interior dot / When encoded
    out = encode_project_key(Path("/srv/my.project/src"))
    # Then only the segment-leading dot rule applies (none here)
    assert out == "srv-my.project-src"


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


def test_path_accessors(tmp_path: Path) -> None:
    """Verify the path properties point at the expected store locations."""
    # Given a store rooted at tmp dirs
    store = store_at(tmp_path)
    # Then each accessor composes the right path
    assert store.learnings_dir == tmp_path / "data" / "learnings"
    assert store.backlog_path == tmp_path / "data" / "backlog.md"
    assert store.handoff_path == tmp_path / "data" / "HANDOFF.md"
    assert store.lock_path == tmp_path / "state" / "sweep.lock"
    assert store.transcript_pointer_path == tmp_path / "state" / "transcript-path"
    assert store.log_path == tmp_path / "state" / "sweep.log"


def test_save_and_read_transcript_pointer(tmp_path: Path) -> None:
    """Verify the transcript pointer round-trips through the state dir."""
    # Given a store with no state dir yet
    store = store_at(tmp_path)
    # When saving a transcript path
    store.save_transcript_pointer("/tmp/x/t.jsonl")  # noqa: S108
    # Then it is read back verbatim (mkdir handled internally)
    assert store.read_transcript_pointer() == "/tmp/x/t.jsonl"  # noqa: S108


def test_read_transcript_pointer_missing_returns_empty(tmp_path: Path) -> None:
    """Verify reading an absent pointer returns '' rather than raising."""
    # Given a store whose pointer was never written
    store = store_at(tmp_path)
    # Then reading fails open to an empty string
    assert store.read_transcript_pointer() == ""


def _seed_handoff(store: Store, text: str) -> None:
    store.data_dir.mkdir(parents=True, exist_ok=True)
    store.handoff_path.write_text(text, encoding="utf-8")


def test_read_handoff_returns_contents(tmp_path: Path) -> None:
    """Verify read_handoff returns the handoff contents verbatim when present."""
    # Given a store with a seeded handoff
    store = store_at(tmp_path)
    _seed_handoff(store, "# Handoff\nbody")
    # Then the contents come back verbatim
    assert store.read_handoff() == "# Handoff\nbody"


def test_read_handoff_missing_returns_none(tmp_path: Path) -> None:
    """Verify read_handoff fails open to None when no handoff exists."""
    # Given a store with no handoff
    store = store_at(tmp_path)
    # Then reading returns None rather than raising
    assert store.read_handoff() is None


def test_read_handoff_empty_returns_none(tmp_path: Path) -> None:
    """Verify an empty handoff file reads as None (nothing to carry)."""
    # Given a store with an empty handoff file
    store = store_at(tmp_path)
    _seed_handoff(store, "")
    # Then it is treated as nothing to carry
    assert store.read_handoff() is None


def test_read_handoff_invalid_utf8_returns_none(tmp_path: Path) -> None:
    """Verify a handoff with invalid UTF-8 fails open to None rather than raising."""
    # Given a store whose handoff holds bytes that are not valid UTF-8
    store = store_at(tmp_path)
    store.data_dir.mkdir(parents=True, exist_ok=True)
    store.handoff_path.write_bytes(b"\xff\xfe bad bytes")
    # Then reading it is nothing-to-carry, not a crash
    assert store.read_handoff() is None


def test_delete_handoff_removes_file(tmp_path: Path) -> None:
    """Verify delete_handoff removes the handoff file."""
    # Given a store with a seeded handoff
    store = store_at(tmp_path)
    _seed_handoff(store, "x")
    # When deleting it
    store.delete_handoff()
    # Then the file is gone
    assert not store.handoff_path.exists()


def test_delete_handoff_missing_is_noop(tmp_path: Path) -> None:
    """Verify delete_handoff is a no-op (never raises) when the file is already gone."""
    # Given a store with no handoff
    store = store_at(tmp_path)
    # Then deleting it does not raise
    store.delete_handoff()
    assert not store.handoff_path.exists()


def test_save_transcript_pointer_ignores_empty(tmp_path: Path) -> None:
    """Verify saving an empty transcript path writes nothing."""
    # Given a store
    store = store_at(tmp_path)
    # When saving an empty path
    store.save_transcript_pointer("")
    # Then no pointer file is created
    assert not store.transcript_pointer_path.exists()


def test_is_empty_true_when_no_artifacts(tmp_path: Path) -> None:
    """Verify is_empty reports True when no memory artifacts exist."""
    # Given a store with an empty (absent) data dir
    store = store_at(tmp_path)
    # Then the store is empty
    assert store.is_empty() is True


def test_is_empty_false_with_a_learning(tmp_path: Path) -> None:
    """Verify is_empty reports False once a learning file exists."""
    # Given a store whose learnings dir holds one file
    store = store_at(tmp_path)
    store.learnings_dir.mkdir(parents=True)
    (store.learnings_dir / "x.md").write_text("body", encoding="utf-8")
    # Then the store is not empty
    assert store.is_empty() is False


def test_processed_round_trip(tmp_path: Path) -> None:
    """Verify processed session IDs round-trip and deduplicate on re-add."""
    # Given a fresh store
    store = store_at(tmp_path)
    # When two session ids are recorded
    store.add_processed("aaa")
    store.add_processed("bbb")
    # Then both read back and the set is deduped on re-add
    store.add_processed("aaa")
    assert store.read_processed() == {"aaa", "bbb"}


def test_read_processed_missing_is_empty(tmp_path: Path) -> None:
    """Verify reading the ledger yields an empty set when no ledger exists."""
    # Given a store with no ledger written yet
    store = store_at(tmp_path)
    # Then reading the ledger yields an empty set, not an error
    assert store.read_processed() == set()


def test_bootstrap_dir_under_state(tmp_path: Path) -> None:
    """Verify the bootstrap scratch dir lives under state_dir."""
    # Given a store
    store = store_at(tmp_path)
    # Then the bootstrap scratch dir lives under state_dir
    assert store.bootstrap_dir == store.state_dir / "bootstrap"


def test_add_processed_many_batches_and_dedups(tmp_path: Path) -> None:
    """Verify add_processed_many records only genuinely new ids and returns that count."""
    # Given a store with one id already recorded
    store = store_at(tmp_path)
    store.add_processed("a")
    # When a batch overlapping the existing id (and carrying a duplicate) is added
    added = store.add_processed_many(["a", "b", "b", "c"])
    # Then only the new ids are recorded, each once, and the new count is returned
    assert added == 2
    assert store.read_processed() == {"a", "b", "c"}
