"""Profile-tier constant tests."""

from __future__ import annotations

import importlib
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path
    from types import ModuleType


def load_profiles(hooks_dir: Path) -> ModuleType:
    """Import lib.profiles with the hooks dir on sys.path."""
    sys.path.insert(0, str(hooks_dir))
    try:
        return importlib.import_module("lib.profiles")
    finally:
        sys.path.pop(0)


def test_all_contains_every_tier(hooks_dir: Path) -> None:
    """Verify ALL contains every profile tier."""
    profiles = load_profiles(hooks_dir)
    assert frozenset({"minimal", "standard", "strict"}) == profiles.ALL


def test_standard_up_excludes_minimal(hooks_dir: Path) -> None:
    """Verify STANDARD_UP excludes minimal."""
    profiles = load_profiles(hooks_dir)
    assert frozenset({"standard", "strict"}) == profiles.STANDARD_UP
    assert "minimal" not in profiles.STANDARD_UP
