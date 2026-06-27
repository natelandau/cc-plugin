"""Shared fixtures for natelandau-recall hook tests."""

from __future__ import annotations

import importlib
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


@pytest.fixture
def import_recall_module(recall_hooks_dir: Path) -> Callable[[str], ModuleType]:
    """Import a recall hooks module by dotted name with recall's lib isolated on sys.path.

    The recall hooks dir is inserted at sys.path[0] so the module's own
    `from lib import ...` siblings resolve to the RECALL lib, not the toolkit
    lib of the same name. Snapshots sys.path and every `lib`/`lib.*`
    sys.modules entry, evicts them, imports, then restores in a finally.
    The returned module keeps working after restore because its sibling
    references are already bound to the recall module objects.
    """

    def _import(dotted: str) -> ModuleType:
        hooks = str(recall_hooks_dir)
        saved_path = list(sys.path)
        saved_lib = {k: v for k, v in sys.modules.items() if k == "lib" or k.startswith("lib.")}
        for k in list(sys.modules):
            if k == "lib" or k.startswith("lib."):
                del sys.modules[k]
        sys.path.insert(0, hooks)
        try:
            return importlib.import_module(dotted)
        finally:
            sys.path[:] = saved_path
            for k in list(sys.modules):
                if k == "lib" or k.startswith("lib."):
                    del sys.modules[k]
            sys.modules.update(saved_lib)

    return _import
