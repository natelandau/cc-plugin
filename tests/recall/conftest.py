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
    sys.path. Registers the module under a qualified key before exec so that
    slotted frozen dataclasses can resolve their own class mid-exec.
    """

    def _load(*parts: str) -> ModuleType:
        path = recall_hooks_dir.joinpath(*parts)
        spec = importlib.util.spec_from_file_location(path.stem, path)
        assert spec
        assert spec.loader
        mod = importlib.util.module_from_spec(spec)
        # Qualified key prevents shadowing real modules; popped on failure to
        # avoid leaking a half-built module into a later test.
        key = f"recall_test_{path.stem}"
        sys.modules[key] = mod
        try:
            spec.loader.exec_module(mod)
        except BaseException:
            sys.modules.pop(key, None)
            raise
        return mod

    return _load
