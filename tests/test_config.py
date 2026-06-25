"""Unit tests for hooks/lib/config.py cascade and resilience."""

from __future__ import annotations

import importlib.util
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path
    from types import ModuleType

    import pytest


def _load_config_mod(hooks_dir: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "_config_under_test", hooks_dir / "lib" / "config.py"
    )
    assert spec
    assert spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_defaults_when_no_files(hooks_dir: Path, tmp_path: Path) -> None:
    """Verify defaults apply when neither config file exists."""
    cfg = _load_config_mod(hooks_dir).load_config(home=tmp_path, project_dir=str(tmp_path))
    assert cfg.profile == "standard"
    assert cfg.disabled_hooks == frozenset()
    assert cfg.option("capture-followups", "backlog", ".agent/BACKLOG.md") == ".agent/BACKLOG.md"


def test_project_overrides_global_scalar(hooks_dir: Path, tmp_path: Path) -> None:
    """Verify project profile replaces the global profile."""
    home = tmp_path / "home"
    proj = tmp_path / "proj"
    _write(home / ".claude" / "natelandau-toolkit.toml", 'profile = "minimal"\n')
    _write(proj / ".claude" / "natelandau-toolkit.toml", 'profile = "strict"\n')
    cfg = _load_config_mod(hooks_dir).load_config(home=home, project_dir=str(proj))
    assert cfg.profile == "strict"


def test_hook_tables_deep_merge(hooks_dir: Path, tmp_path: Path) -> None:
    """Verify project overrides one hook table key without wiping siblings."""
    home = tmp_path / "home"
    proj = tmp_path / "proj"
    _write(
        home / ".claude" / "natelandau-toolkit.toml",
        '[hooks.capture-followups]\nbacklog = "home.md"\nextra = "keep"\n',
    )
    _write(
        proj / ".claude" / "natelandau-toolkit.toml",
        '[hooks.capture-followups]\nbacklog = "proj.md"\n',
    )
    cfg = _load_config_mod(hooks_dir).load_config(home=home, project_dir=str(proj))
    assert cfg.option("capture-followups", "backlog", "x") == "proj.md"
    assert cfg.option("capture-followups", "extra", "x") == "keep"


def test_malformed_toml_falls_back_no_raise(hooks_dir: Path, tmp_path: Path) -> None:
    """Verify malformed TOML is ignored rather than raising."""
    proj = tmp_path / "proj"
    _write(proj / ".claude" / "natelandau-toolkit.toml", "profile = = broken\n")
    cfg = _load_config_mod(hooks_dir).load_config(home=tmp_path, project_dir=str(proj))
    assert cfg.profile == "standard"


def test_unknown_profile_falls_back(hooks_dir: Path, tmp_path: Path) -> None:
    """Verify an unknown profile value falls back to standard."""
    proj = tmp_path / "proj"
    _write(proj / ".claude" / "natelandau-toolkit.toml", 'profile = "turbo"\n')
    cfg = _load_config_mod(hooks_dir).load_config(home=tmp_path, project_dir=str(proj))
    assert cfg.profile == "standard"


def test_disabled_hooks_list_replaced_by_project(hooks_dir: Path, tmp_path: Path) -> None:
    """Verify project disabled_hooks replaces the global list."""
    home = tmp_path / "home"
    proj = tmp_path / "proj"
    _write(home / ".claude" / "natelandau-toolkit.toml", 'disabled_hooks = ["use-uv"]\n')
    _write(proj / ".claude" / "natelandau-toolkit.toml", 'disabled_hooks = ["commit-message"]\n')
    cfg = _load_config_mod(hooks_dir).load_config(home=home, project_dir=str(proj))
    assert cfg.disabled_hooks == frozenset({"commit-message"})


def test_project_dir_populated_from_override(hooks_dir: Path, tmp_path: Path) -> None:
    """Verify load_config records the resolved project_dir on the Config."""
    # Given no config files, only a project dir override
    proj = tmp_path / "proj"

    # When loading config with that project dir
    cfg = _load_config_mod(hooks_dir).load_config(home=tmp_path, project_dir=str(proj))

    # Then the resolved project_dir is carried on the Config
    assert cfg.project_dir == str(proj)


def test_project_dir_none_when_unset(
    hooks_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify project_dir is None when no project dir is resolved."""
    # Given neither an override nor the env var
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)

    # When loading config with project_dir explicitly empty
    cfg = _load_config_mod(hooks_dir).load_config(home=tmp_path, project_dir=None)

    # Then project_dir is None
    assert cfg.project_dir is None
