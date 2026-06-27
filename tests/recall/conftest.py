"""Shared fixtures for natelandau-recall hook tests."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def recall_hooks_dir() -> Path:
    """Resolve the recall plugin's hooks directory."""
    return Path(__file__).resolve().parent.parent.parent / "plugins" / "natelandau-recall" / "hooks"
