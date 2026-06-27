"""Shared fixtures for natelandau-recall hook tests.

The recall hooks dir is placed on sys.path so tests import the engine directly
as `from recall.store import Store`. The package name is unique to this plugin,
so it never collides with the toolkit's `lib` package even in one pytest process
(and `tests/` is itself a package, so `tests.recall` never shadows `recall`).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_RECALL_HOOKS = (
    Path(__file__).resolve().parent.parent.parent / "plugins" / "natelandau-recall" / "hooks"
)
if str(_RECALL_HOOKS) not in sys.path:
    sys.path.insert(0, str(_RECALL_HOOKS))


@pytest.fixture(scope="session")
def recall_hooks_dir() -> Path:
    """Resolve the recall plugin's hooks directory."""
    return _RECALL_HOOKS
