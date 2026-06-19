# tests/test_registry.py
"""Unit tests for hooks/lib/registry.py gating and routing."""

from __future__ import annotations

import importlib
import sys
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path
    from types import ModuleType


@pytest.fixture
def reg(hooks_dir: Path) -> ModuleType:
    """Import the registry with the hooks dir on sys.path."""
    sys.path.insert(0, str(hooks_dir))
    try:
        return importlib.import_module("lib.registry")
    finally:
        sys.path.pop(0)


def _cfg(reg: ModuleType, profile: str, disabled: frozenset[str] = frozenset()) -> object:
    from lib.config import Config  # type: ignore[import-not-found]  # ty: ignore[unresolved-import]

    return Config(profile=profile, disabled_hooks=frozenset(disabled), hook_options={})


def test_minimal_excludes_advisory(reg: ModuleType) -> None:
    """Verify minimal profile drops use-uv and commit-message but keeps safety."""
    ids = {c.id for c in reg.applicable_checks("Bash", _cfg(reg, "minimal"))}
    assert "branch-protection" in ids
    assert "protect-system" in ids
    assert "use-uv" not in ids
    assert "commit-message" not in ids


def test_standard_includes_all_bash(reg: ModuleType) -> None:
    """Verify standard profile includes every Bash check."""
    ids = {c.id for c in reg.applicable_checks("Bash", _cfg(reg, "standard"))}
    assert {
        "branch-protection",
        "protect-secrets",
        "protect-system",
        "commit-message",
        "use-uv",
    } <= ids


def test_disabled_hook_removed_even_in_strict(reg: ModuleType) -> None:
    """Verify a disabled hook is dropped at strict profile."""
    ids = {
        c.id
        for c in reg.applicable_checks("Bash", _cfg(reg, "strict", frozenset({"protect-system"})))
    }
    assert "protect-system" not in ids


def test_read_routes_only_secrets(reg: ModuleType) -> None:
    """Verify Read routes solely to protect-secrets."""
    ids = {c.id for c in reg.applicable_checks("Read", _cfg(reg, "standard"))}
    assert ids == {"protect-secrets"}


def test_safety_first_ordering(reg: ModuleType) -> None:
    """Verify advisory use-uv sorts after the blocking checks."""
    order = [c.id for c in reg.applicable_checks("Bash", _cfg(reg, "standard"))]
    assert order.index("use-uv") == len(order) - 1
    assert order.index("branch-protection") < order.index("use-uv")
