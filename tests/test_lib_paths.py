"""Unit tests for hooks/lib/paths.py: symlink-escape-hardened containment.

Exercises `realpath_nearest_existing` (missing tails, symlinked intermediates),
`is_within_root`, and the fail-closed `assert_within_root` guard. Imported
in-process with the hooks dir on sys.path, like the other lib suites.
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
def paths(hooks_dir: Path) -> ModuleType:
    """Import lib.paths with the hooks dir on sys.path."""
    sys.path.insert(0, str(hooks_dir))
    try:
        return importlib.import_module("lib.paths")
    finally:
        sys.path.pop(0)


# --- realpath_nearest_existing ---------------------------------------------


def test_realpath_nearest_existing_existing_file(paths: ModuleType, tmp_path: Path) -> None:
    """Verify an existing file canonicalizes to its resolved path."""
    # Given an existing file
    target = tmp_path / "real.txt"
    target.write_text("x", encoding="utf-8")

    # When canonicalizing it
    result = paths.realpath_nearest_existing(target)

    # Then it equals the fully resolved path
    assert result == target.resolve()


def test_realpath_nearest_existing_missing_tail(paths: ModuleType, tmp_path: Path) -> None:
    """Verify a not-yet-existing leaf under a real dir keeps the dir's realpath."""
    # Given an existing dir and a missing child
    target = tmp_path / "child" / "leaf.json"

    # When canonicalizing the missing path
    result = paths.realpath_nearest_existing(target)

    # Then the existing ancestor is resolved and the tail re-appended
    assert result == tmp_path.resolve() / "child" / "leaf.json"


def test_realpath_nearest_existing_resolves_symlinked_intermediate(
    paths: ModuleType, tmp_path: Path
) -> None:
    """Verify a symlinked intermediate directory is resolved, not trusted."""
    # Given a real target dir and a symlink pointing at it
    real_dir = tmp_path / "real_dir"
    real_dir.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real_dir, target_is_directory=True)

    # When canonicalizing a missing file reached through the symlink
    result = paths.realpath_nearest_existing(link / "new.json")

    # Then the symlink is resolved to its real target
    assert result == real_dir.resolve() / "new.json"


# --- is_within_root --------------------------------------------------------


def test_is_within_root_contained(paths: ModuleType, tmp_path: Path) -> None:
    """Verify a child path reports as within the root."""
    # Given a root and a child beneath it
    root = tmp_path / "root"
    root.mkdir()

    # When checking containment of a (missing) child
    # Then it is within the root
    assert paths.is_within_root(root / "a" / "b.json", root) is True


def test_is_within_root_root_itself(paths: ModuleType, tmp_path: Path) -> None:
    """Verify the root path counts as within itself."""
    # Given a root
    root = tmp_path / "root"
    root.mkdir()

    # When checking the root against itself
    # Then it is within
    assert paths.is_within_root(root, root) is True


def test_is_within_root_sibling_escapes(paths: ModuleType, tmp_path: Path) -> None:
    """Verify a sibling outside the root is not contained."""
    # Given a root and a sibling directory
    root = tmp_path / "root"
    root.mkdir()
    sibling = tmp_path / "other" / "secret.json"

    # When checking the sibling
    # Then it is not within the root
    assert paths.is_within_root(sibling, root) is False


def test_is_within_root_symlink_escape(paths: ModuleType, tmp_path: Path) -> None:
    """Verify a symlink inside the root pointing out is not contained."""
    # Given a root that contains a symlink to an outside directory
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    escape = root / "escape"
    escape.symlink_to(outside, target_is_directory=True)

    # When checking a file reached through the escaping symlink
    # Then containment fails because the symlink resolves outside the root
    assert paths.is_within_root(escape / "loot.json", root) is False


# --- assert_within_root ----------------------------------------------------


def test_assert_within_root_returns_canonical(paths: ModuleType, tmp_path: Path) -> None:
    """Verify a contained target returns its canonicalized path."""
    # Given a root and a contained missing child
    root = tmp_path / "root"
    root.mkdir()

    # When asserting containment
    result = paths.assert_within_root(root / "x.json", root)

    # Then the canonical contained path is returned
    assert result == root.resolve() / "x.json"


def test_assert_within_root_raises_on_escape(paths: ModuleType, tmp_path: Path) -> None:
    """Verify an escaping target raises PathEscapeError."""
    # Given a root and an outside target
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside" / "x.json"

    # When asserting containment of the outside target
    # Then it raises the fail-closed error
    with pytest.raises(paths.PathEscapeError):
        paths.assert_within_root(outside, root)
