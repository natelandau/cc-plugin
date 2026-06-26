"""Unit tests for hooks/lib/state.py: the session-keyed JSON state bridge.

Exercises read/write roundtrips, fail-open on corrupt/missing files, the
once-per-session `should_emit_once` debounce, session-id sanitizing, and that a
crafted (traversal) session id stays contained in the state root. Every test
points the bridge at a tmp_path root so the real temp dir is never touched.
"""

from __future__ import annotations

import importlib
import sys
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path
    from types import ModuleType


@pytest.fixture
def state(hooks_dir: Path) -> ModuleType:
    """Import lib.state with the hooks dir on sys.path."""
    sys.path.insert(0, str(hooks_dir))
    try:
        return importlib.import_module("lib.state")
    finally:
        sys.path.pop(0)


# --- read/write roundtrip --------------------------------------------------


def test_write_then_read_roundtrip(state: ModuleType, tmp_path: Path) -> None:
    """Verify a written bridge record reads back identically."""
    # Given a record written for a session
    assert state.write_state("sess-1", {"seen": ["a", "b"]}, root=tmp_path) is True

    # When reading it back
    result = state.read_state("sess-1", root=tmp_path)

    # Then it matches what was written
    assert result == {"seen": ["a", "b"]}


def test_read_missing_returns_empty(state: ModuleType, tmp_path: Path) -> None:
    """Verify reading a never-written session yields an empty dict."""
    # Given no bridge file for the session
    # When reading it
    # Then the read fails open to {}
    assert state.read_state("never", root=tmp_path) == {}


def test_read_corrupt_file_returns_empty(state: ModuleType, tmp_path: Path) -> None:
    """Verify a malformed bridge file reads as empty rather than raising."""
    # Given a corrupt bridge file at the session's path
    path = state.bridge_path("sess-1", root=tmp_path)
    assert path is not None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")

    # When reading it
    # Then it fails open to {}
    assert state.read_state("sess-1", root=tmp_path) == {}


def test_read_non_object_returns_empty(state: ModuleType, tmp_path: Path) -> None:
    """Verify a JSON array (non-object) bridge file reads as empty."""
    # Given a bridge file holding a JSON array
    path = state.bridge_path("sess-1", root=tmp_path)
    assert path is not None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[1, 2, 3]", encoding="utf-8")

    # When reading it
    # Then a non-object value fails open to {}
    assert state.read_state("sess-1", root=tmp_path) == {}


def test_read_non_utf8_returns_empty(state: ModuleType, tmp_path: Path) -> None:
    """Verify a non-UTF-8 bridge file fails open instead of raising UnicodeDecodeError."""
    # Given a bridge file holding invalid UTF-8 bytes
    path = state.bridge_path("sess-1", root=tmp_path)
    assert path is not None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xff\xfe not utf-8")

    # When reading it
    # Then the UnicodeDecodeError is caught and it fails open to {}
    assert state.read_state("sess-1", root=tmp_path) == {}


def test_read_oversized_returns_empty(state: ModuleType, tmp_path: Path) -> None:
    """Verify a file past MAX_STATE_BYTES fails open without being fully trusted."""
    # Given a bridge file larger than the cap
    path = state.bridge_path("sess-1", root=tmp_path)
    assert path is not None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("0" * (state.MAX_STATE_BYTES + 10), encoding="utf-8")

    # When reading it
    # Then the oversized read is rejected to {}
    assert state.read_state("sess-1", root=tmp_path) == {}


def test_write_state_non_serializable_returns_false_no_orphan(
    state: ModuleType, tmp_path: Path
) -> None:
    """Verify a non-serializable record returns False and leaves no temp file behind."""
    # Given a record that json cannot serialize
    result = state.write_state("sess-1", {"bad": object()}, root=tmp_path)

    # Then the write fails open and the state dir holds no orphaned temp file
    assert result is False
    leftover = list(tmp_path.rglob(".tmp-*"))
    assert leftover == [], f"orphaned temp files: {leftover}"


# --- should_emit_once ------------------------------------------------------


def test_should_emit_once_first_true_second_false(state: ModuleType, tmp_path: Path) -> None:
    """Verify a signature emits once then is suppressed within a session."""
    # Given a fresh session
    # When the same signature is checked twice
    first = state.should_emit_once("sess-1", "use-uv:pytest", root=tmp_path)
    second = state.should_emit_once("sess-1", "use-uv:pytest", root=tmp_path)

    # Then it fires the first time and is suppressed the second
    assert first is True
    assert second is False


def test_should_emit_once_distinct_signatures_each_fire(state: ModuleType, tmp_path: Path) -> None:
    """Verify different signatures each fire once independently."""
    # Given one session
    # When two distinct signatures are checked
    a = state.should_emit_once("sess-1", "use-uv:pytest", root=tmp_path)
    b = state.should_emit_once("sess-1", "use-uv:ruff", root=tmp_path)

    # Then each fires on its own first occurrence
    assert a is True
    assert b is True


def test_should_emit_once_distinct_sessions_each_fire(state: ModuleType, tmp_path: Path) -> None:
    """Verify the same signature fires once per session, not globally."""
    # Given the same signature seen in two sessions
    # When checked in each
    s1 = state.should_emit_once("sess-1", "use-uv:pytest", root=tmp_path)
    s2 = state.should_emit_once("sess-2", "use-uv:pytest", root=tmp_path)

    # Then both fire because debounce is per-session
    assert s1 is True
    assert s2 is True


def test_should_emit_once_no_session_always_true(state: ModuleType, tmp_path: Path) -> None:
    """Verify an empty session id never suppresses (always emits)."""
    # Given no session id to key on
    # When the same signature is checked repeatedly
    # Then it always fires
    assert state.should_emit_once("", "use-uv:pytest", root=tmp_path) is True
    assert state.should_emit_once("", "use-uv:pytest", root=tmp_path) is True


def test_should_emit_once_bounds_seen_list(state: ModuleType, tmp_path: Path) -> None:
    """Verify the recorded seen list is capped at MAX_SEEN entries."""
    # Given more distinct signatures than the cap
    for i in range(state.MAX_SEEN + 50):
        state.should_emit_once("sess-1", f"sig-{i}", root=tmp_path)

    # When inspecting the persisted record
    seen = state.read_state("sess-1", root=tmp_path)["seen"]

    # Then it is bounded to the most recent MAX_SEEN entries
    assert len(seen) == state.MAX_SEEN
    assert seen[-1] == f"sig-{state.MAX_SEEN + 49}"


# --- session-id sanitizing / containment -----------------------------------


def test_bridge_path_within_root_for_traversal_id(state: ModuleType, tmp_path: Path) -> None:
    """Verify a traversal-laden session id stays contained in the state root."""
    # Given a hostile session id
    path = state.bridge_path("../../etc/passwd", root=tmp_path)

    # When resolving its bridge path
    # Then it sanitizes to a contained file under the root
    assert path is not None
    assert tmp_path.resolve() in path.parents


def test_bridge_path_empty_after_sanitize_is_none(state: ModuleType, tmp_path: Path) -> None:
    """Verify an id that sanitizes to empty yields no bridge path."""
    # Given an id made entirely of stripped characters
    # When resolving its bridge path
    # Then there is nothing to key on
    assert state.bridge_path("///", root=tmp_path) is None


def test_non_string_session_id_fails_open(state: ModuleType, tmp_path: Path) -> None:
    """Verify a non-string session id never raises and always emits."""
    # Given a malformed (non-string) session id
    # When it reaches the bridge and the debounce
    # Then both fail open rather than raising a TypeError
    assert state.bridge_path(12345, root=tmp_path) is None  # type: ignore[arg-type]
    assert state.should_emit_once(12345, "use-uv:pytest", root=tmp_path) is True  # type: ignore[arg-type]
