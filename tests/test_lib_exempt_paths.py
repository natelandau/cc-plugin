"""Unit tests for hooks/lib/exempt_paths.py: the two-source path exemption.

Exercises `resolve()` over both sources -- the `exempt_paths` list from the
global config and the `$NATELANDAU_TOOLKIT_EXEMPT_PATHS` variable -- including
the entries that must contribute no root, then `ExemptRoots.contains()` across
relative paths and symlinks. Imported in-process with the hooks dir on
sys.path, like the other lib suites.
"""

from __future__ import annotations

import importlib
import os
import sys
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path
    from types import ModuleType


@pytest.fixture
def exempt_paths(monkeypatch: pytest.MonkeyPatch, hooks_dir: Path) -> ModuleType:
    """Import lib.exempt_paths with the environment source cleared.

    Starting from an unset variable means each test declares exactly the roots
    it needs, so a developer's own exported value can never satisfy one.
    """
    sys.path.insert(0, str(hooks_dir))
    try:
        module = importlib.import_module("lib.exempt_paths")
    finally:
        sys.path.pop(0)
    monkeypatch.delenv(module.ENV_VAR, raising=False)
    return module


def _env_value(*paths: Path) -> str:
    """Join paths the way a user would write the variable."""
    return os.pathsep.join(str(p) for p in paths)


# --- resolve ---------------------------------------------------------------


def test_resolve_nothing_configured(exempt_paths: ModuleType) -> None:
    """Verify no roots are found when neither source holds an entry."""
    # Given no config list and no variable

    # When resolving
    # Then there are no roots
    assert exempt_paths.resolve().roots == ()


def test_resolve_from_config(exempt_paths: ModuleType, tmp_path: Path) -> None:
    """Verify a path from the global config becomes a root."""
    # Given a path in the config list
    store = tmp_path / "store"

    # When resolving
    resolved = exempt_paths.resolve([str(store)])

    # Then the listed path is a root
    assert resolved.roots == (store,)


def test_resolve_from_env_var(
    exempt_paths: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Verify each entry of the variable becomes a root."""
    # Given a variable holding two paths
    first = tmp_path / "first"
    second = tmp_path / "second"
    monkeypatch.setenv(exempt_paths.ENV_VAR, _env_value(first, second))

    # When resolving
    resolved = exempt_paths.resolve()

    # Then both are roots
    assert resolved.roots == (first, second)


def test_resolve_combines_both_sources(
    exempt_paths: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Verify the config list and the variable accumulate rather than override."""
    # Given one root from each source
    configured = tmp_path / "configured"
    from_env = tmp_path / "from_env"
    monkeypatch.setenv(exempt_paths.ENV_VAR, _env_value(from_env))

    # When resolving
    resolved = exempt_paths.resolve([str(configured)])

    # Then both are present
    assert resolved.roots == (configured, from_env)


@pytest.mark.parametrize(
    ("value", "case"),
    [
        ("", "empty"),
        ("   ", "whitespace only"),
        ("relative/store", "relative path"),
        ("/", "filesystem root"),
        ("/..", "filesystem root spelled with .."),
        ("/store/../..", "traversal above a named tree"),
        ("~nosuchuser42/store", "tilde naming no account"),
    ],
)
def test_resolve_drops_unusable_entries(exempt_paths: ModuleType, value: str, case: str) -> None:
    """Verify an entry that cannot name one tree is dropped rather than widened."""
    # Given an unusable entry and no other
    # When resolving
    # Then it contributes nothing, so nothing becomes exempt
    assert exempt_paths.resolve([value]).roots == (), case


def test_resolve_keeps_neighbors_of_an_unusable_entry(
    exempt_paths: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Verify one bad entry does not void the rest of the list."""
    # Given a variable whose middle entry is unusable
    good = tmp_path / "good"
    other = tmp_path / "other"
    monkeypatch.setenv(
        exempt_paths.ENV_VAR, os.pathsep.join([str(good), "relative/bad", str(other)])
    )

    # When resolving
    resolved = exempt_paths.resolve()

    # Then the usable neighbors survive
    assert resolved.roots == (good, other)


def test_resolve_ignores_an_empty_env_var(
    exempt_paths: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify an exported but empty variable yields no root.

    Splitting "" produces one empty segment, so this is the case that would
    otherwise turn an unset composition (`export VAR="$UNSET"`) into a root.
    """
    # Given the variable exported with no value
    monkeypatch.setenv(exempt_paths.ENV_VAR, "")

    # When resolving
    # Then there are no roots
    assert exempt_paths.resolve().roots == ()


def test_resolve_expands_user(exempt_paths: ModuleType) -> None:
    """Verify a `~`-prefixed entry expands to the home directory."""
    # Given an entry written with a tilde
    # When resolving
    roots = exempt_paths.resolve(["~/store"]).roots

    # Then the tilde is expanded, so the root is absolute and usable
    assert len(roots) == 1
    assert roots[0].is_absolute()
    assert roots[0].name == "store"


# --- ExemptRoots.contains --------------------------------------------------


def test_contains_nothing_configured(exempt_paths: ModuleType, tmp_path: Path) -> None:
    """Verify nothing is contained when no root is configured."""
    # Given no roots
    # When testing any path
    # Then it is not exempt
    assert exempt_paths.ExemptRoots().contains(str(tmp_path / "note.md")) is False


@pytest.mark.parametrize(
    "relpath",
    [
        "",  # the root directory itself
        "note.md",  # a file directly inside
        "nested/deep/note.md",  # a file that does not exist yet
    ],
)
def test_contains_paths_inside(exempt_paths: ModuleType, tmp_path: Path, relpath: str) -> None:
    """Verify a root and everything beneath it is contained."""
    # Given a resolved root
    store = tmp_path / "store"
    store.mkdir()
    resolved = exempt_paths.resolve([str(store)])

    # When testing a path at or under the root
    target = store / relpath if relpath else store

    # Then it is contained
    assert resolved.contains(str(target)) is True


def test_contains_path_outside(exempt_paths: ModuleType, tmp_path: Path) -> None:
    """Verify a sibling sharing the root's name prefix is not contained."""
    # Given a resolved root and a sibling directory
    store = tmp_path / "store"
    store.mkdir()
    sibling = tmp_path / "store_backup"
    sibling.mkdir()
    resolved = exempt_paths.resolve([str(store)])

    # When testing the sibling
    # Then it is not contained
    assert resolved.contains(str(sibling / "note.md")) is False


def test_contains_matches_any_resolved_root(exempt_paths: ModuleType, tmp_path: Path) -> None:
    """Verify a path under the second of several roots is still contained."""
    # Given two resolved roots
    first = tmp_path / "first"
    second = tmp_path / "second"
    resolved = exempt_paths.resolve([str(first), str(second)])

    # When testing a path under the later one
    # Then it is contained
    assert resolved.contains(str(second / "note.md")) is True


def test_contains_relative_path_anchored_to_cwd(exempt_paths: ModuleType, tmp_path: Path) -> None:
    """Verify a relative path resolves against the supplied cwd."""
    # Given a resolved root
    store = tmp_path / "store"
    store.mkdir()
    resolved = exempt_paths.resolve([str(store)])

    # When testing the same relative path from inside and outside the root
    # Then only the one anchored inside is contained
    assert resolved.contains("note.md", str(store)) is True
    assert resolved.contains("note.md", str(tmp_path)) is False


def test_contains_symlink_into_root(exempt_paths: ModuleType, tmp_path: Path) -> None:
    """Verify a symlink pointing into an exempt tree is contained."""
    # Given a resolved root and a symlink to it from outside
    store = tmp_path / "store"
    store.mkdir()
    (store / "note.md").write_text("x", encoding="utf-8")
    link = tmp_path / "link"
    link.symlink_to(store)
    resolved = exempt_paths.resolve([str(store)])

    # When testing a path that traverses the symlink
    # Then it resolves inside the root
    assert resolved.contains(str(link / "note.md")) is True


def test_contains_traversal_out_of_root(exempt_paths: ModuleType, tmp_path: Path) -> None:
    """Verify a `..` traversal escaping an exempt tree is not contained."""
    # Given a resolved root
    store = tmp_path / "store"
    store.mkdir()
    resolved = exempt_paths.resolve([str(store)])

    # When testing a path that climbs back out
    # Then it is not contained
    assert resolved.contains(str(store / ".." / "outside.md")) is False


def test_resolve_survives_an_unexpandable_tilde(
    exempt_paths: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Verify a tilde entry naming no account drops itself, not the whole resolution.

    Resolution runs before any guard check, so an entry that raised while
    expanding would take the calling hook down with it and silently allow
    everything it protects.
    """
    # Given a variable whose first entry names an account that does not exist
    good = tmp_path / "good"
    monkeypatch.setenv(exempt_paths.ENV_VAR, os.pathsep.join(["~nosuchuser42/store", str(good)]))

    # When resolving
    resolved = exempt_paths.resolve()

    # Then the usable neighbor survives and nothing raises
    assert resolved.roots == (good,)


def test_contains_survives_an_unexpandable_tilde(exempt_paths: ModuleType, tmp_path: Path) -> None:
    """Verify a tilde path naming no account is simply not contained."""
    # Given a resolved root
    store = tmp_path / "store"
    store.mkdir()
    resolved = exempt_paths.resolve([str(store)])

    # When testing a path for an account that does not exist
    # Then it is not contained rather than raising
    assert resolved.contains("~nosuchuser42/store/note.md") is False
