"""Verify recall config cascade and the headless guard."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path
    from types import ModuleType

    import pytest


def test_load_config_defaults_to_standard_profile(
    load_recall_module: Callable[..., ModuleType], tmp_path: Path
) -> None:
    """Verify an absent config yields the standard profile and empty disables."""
    # Given no config files anywhere
    config = load_recall_module("lib", "config.py")

    # When config loads with isolated home/project
    cfg = config.load_config(home=tmp_path / "home", project_dir=str(tmp_path / "proj"))

    # Then defaults apply
    assert cfg.profile == "standard"
    assert cfg.disabled_hooks == frozenset()


def test_int_option_parses_and_falls_back(
    load_recall_module: Callable[..., ModuleType], tmp_path: Path
) -> None:
    """Verify int_option reads an int and falls back on bad/absent values."""
    # Given a project config setting one int option and one garbage value
    proj = tmp_path / "proj"
    (proj / ".claude").mkdir(parents=True)
    (proj / ".claude" / "natelandau-recall.toml").write_text(
        '[hooks.sweep]\nmin_exchanges = "7"\narchitecture_max_bytes = "notint"\n',
        encoding="utf-8",
    )
    config = load_recall_module("lib", "config.py")

    # When config loads
    cfg = config.load_config(home=tmp_path / "home", project_dir=str(proj))

    # Then the valid int parses and the invalid one falls back
    assert cfg.int_option("sweep", "min_exchanges", 5) == 7
    assert cfg.int_option("sweep", "architecture_max_bytes", 4096) == 4096


def test_is_headless_reads_env(
    load_recall_module: Callable[..., ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify is_headless reflects NL_RECALL_HEADLESS."""
    headless = load_recall_module("lib", "headless.py")

    # Given the env unset then set
    monkeypatch.delenv(headless.HEADLESS_ENV, raising=False)
    assert headless.is_headless() is False

    # When the guard env is set to 1
    monkeypatch.setenv(headless.HEADLESS_ENV, "1")

    # Then the guard reports headless
    assert headless.is_headless() is True
