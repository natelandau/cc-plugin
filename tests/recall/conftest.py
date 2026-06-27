"""Shared fixtures for natelandau-recall hook tests."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import ModuleType


@pytest.fixture(scope="session")
def recall_hooks_dir() -> Path:
    """Resolve the recall plugin's hooks directory."""
    return Path(__file__).resolve().parent.parent.parent / "plugins" / "natelandau-recall" / "hooks"


@pytest.fixture(scope="session")
def load_recall_module(recall_hooks_dir: Path) -> Callable[..., ModuleType]:
    """Return a loader function for recall lib modules.

    Loads by relative path parts under the recall hooks dir without polluting
    sys.path. The module is named with a qualified key and registered under that
    same key before exec, which (a) prevents shadowing a real stdlib/installed
    module of the same stem, and (b) because the key IS the module's __name__,
    lets a slotted/frozen dataclass resolve its own class via
    sys.modules[cls.__module__] mid-exec (e.g. Config).
    """

    def _load(*parts: str) -> ModuleType:
        path = recall_hooks_dir.joinpath(*parts)
        # Name the spec with the qualified key so __name__ == registration key.
        key = f"recall_test_{path.stem}"
        spec = importlib.util.spec_from_file_location(key, path)
        assert spec
        assert spec.loader
        mod = importlib.util.module_from_spec(spec)
        # Popped on failure to avoid leaking a half-built module into a later test.
        sys.modules[key] = mod
        try:
            spec.loader.exec_module(mod)
        except BaseException:
            sys.modules.pop(key, None)
            raise
        return mod

    return _load
