"""Unit tests for hooks/lib/config.py cascade and resilience."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests._helpers import load_hook_module

if TYPE_CHECKING:
    from pathlib import Path
    from types import ModuleType

    import pytest


def _load_config_mod(hooks_dir: Path) -> ModuleType:
    return load_hook_module(hooks_dir, "lib/config.py", "_config_under_test")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_defaults_when_no_files(hooks_dir: Path, tmp_path: Path) -> None:
    """Verify defaults apply when neither config file exists."""
    cfg = _load_config_mod(hooks_dir).load_config(home=tmp_path, project_dir=str(tmp_path))
    assert cfg.profile == "standard"
    assert cfg.disabled_hooks == frozenset()
    assert cfg.option("branch-protection", "some_key", default="default_val") == "default_val"


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
        '[hooks.protect-secrets]\nsome_key = "home.md"\nextra = "keep"\n',
    )
    _write(
        proj / ".claude" / "natelandau-toolkit.toml",
        '[hooks.protect-secrets]\nsome_key = "proj.md"\n',
    )
    cfg = _load_config_mod(hooks_dir).load_config(home=home, project_dir=str(proj))
    assert cfg.option("protect-secrets", "some_key", default="x") == "proj.md"
    assert cfg.option("protect-secrets", "extra", default="x") == "keep"


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


def test_exempt_paths_read_from_the_global_layer(hooks_dir: Path, tmp_path: Path) -> None:
    """Verify exempt_paths in the global config reaches the resolved Config."""
    # Given a global config listing two exempt trees
    home = tmp_path / "home"
    _write(
        home / ".claude" / "natelandau-toolkit.toml",
        'exempt_paths = ["/a/store", "~/b/store"]\n',
    )

    # When loading the config
    cfg = _load_config_mod(hooks_dir).load_config(home=home, project_dir=str(tmp_path / "proj"))

    # Then both entries are carried verbatim, expansion being the resolver's job
    assert cfg.exempt_paths == ("/a/store", "~/b/store")


def test_exempt_paths_ignored_in_the_project_layer(hooks_dir: Path, tmp_path: Path) -> None:
    """Verify a project config cannot add an exempt tree.

    The project layer is a committed file inside the repository a guard
    protects, so honoring it there would let one repo waive the guard for
    everyone who clones it.
    """
    # Given a project config listing an exempt tree and no global one
    home = tmp_path / "home"
    proj = tmp_path / "proj"
    _write(proj / ".claude" / "natelandau-toolkit.toml", 'exempt_paths = ["/sneaky"]\n')

    # When loading the config
    cfg = _load_config_mod(hooks_dir).load_config(home=home, project_dir=str(proj))

    # Then nothing is exempt
    assert cfg.exempt_paths == ()


def test_project_layer_cannot_clear_global_exempt_paths(hooks_dir: Path, tmp_path: Path) -> None:
    """Verify the project layer neither adds to nor removes from the global list."""
    # Given a global config with an exempt tree and a project config clearing it
    home = tmp_path / "home"
    proj = tmp_path / "proj"
    _write(home / ".claude" / "natelandau-toolkit.toml", 'exempt_paths = ["/a/store"]\n')
    _write(proj / ".claude" / "natelandau-toolkit.toml", "exempt_paths = []\n")

    # When loading the config
    cfg = _load_config_mod(hooks_dir).load_config(home=home, project_dir=str(proj))

    # Then the global list stands
    assert cfg.exempt_paths == ("/a/store",)


def test_exempt_paths_ignores_non_string_entries(hooks_dir: Path, tmp_path: Path) -> None:
    """Verify a malformed entry is dropped without voiding the list."""
    # Given a global config whose list mixes a path with a number
    home = tmp_path / "home"
    _write(home / ".claude" / "natelandau-toolkit.toml", 'exempt_paths = ["/a/store", 7]\n')

    # When loading the config
    cfg = _load_config_mod(hooks_dir).load_config(home=home, project_dir=str(tmp_path / "proj"))

    # Then the usable entry survives
    assert cfg.exempt_paths == ("/a/store",)


def test_exempt_paths_ignores_a_non_list_value(hooks_dir: Path, tmp_path: Path) -> None:
    """Verify a scalar written where a list belongs exempts nothing."""
    # Given a global config with exempt_paths set to a bare string
    home = tmp_path / "home"
    _write(home / ".claude" / "natelandau-toolkit.toml", 'exempt_paths = "/a/store"\n')

    # When loading the config
    cfg = _load_config_mod(hooks_dir).load_config(home=home, project_dir=str(tmp_path / "proj"))

    # Then nothing is exempt
    assert cfg.exempt_paths == ()


def test_trusted_remote_hosts_read_from_the_global_layer(hooks_dir: Path, tmp_path: Path) -> None:
    """Verify trusted_remote_hosts in the global config reaches the resolved Config."""
    # Given a global config trusting two hosts, one non-string entry mixed in
    home = tmp_path / "home"
    _write(
        home / ".claude" / "natelandau-toolkit.toml",
        'trusted_remote_hosts = ["nas", "*.lan", 7]\n',
    )

    # When loading the config
    cfg = _load_config_mod(hooks_dir).load_config(home=home, project_dir=str(tmp_path / "proj"))

    # Then the string entries are carried verbatim
    assert cfg.trusted_remote_hosts == ("nas", "*.lan")


def test_trusted_remote_hosts_ignored_in_the_project_layer(hooks_dir: Path, tmp_path: Path) -> None:
    """Verify a project config can neither add nor clear trusted hosts.

    Trusting a host waives the protect-remote prompt, and the project layer is
    a committed file inside the repository, so honoring it would let one repo
    silence the prompt for everyone who clones it.
    """
    # Given a global list and a project config that tries to replace it
    home = tmp_path / "home"
    proj = tmp_path / "proj"
    _write(home / ".claude" / "natelandau-toolkit.toml", 'trusted_remote_hosts = ["nas"]\n')
    _write(proj / ".claude" / "natelandau-toolkit.toml", 'trusted_remote_hosts = ["prod"]\n')

    # When loading the config
    cfg = _load_config_mod(hooks_dir).load_config(home=home, project_dir=str(proj))

    # Then only the global list stands
    assert cfg.trusted_remote_hosts == ("nas",)


def test_hook_options_typed_values_cascade(hooks_dir: Path, tmp_path: Path) -> None:
    """Verify int, bool, and list options merge per key with the project layer winning."""
    # Given typed options in both layers, the project loosening one global key
    home = tmp_path / "home"
    proj = tmp_path / "proj"
    _write(
        home / ".claude" / "natelandau-toolkit.toml",
        "[hooks.commit-message]\n"
        "max_subject_length = 70\n"
        "force_imperative = true\n"
        'types = ["feat", "fix"]\n',
    )
    _write(
        proj / ".claude" / "natelandau-toolkit.toml",
        "[hooks.commit-message]\nmax_subject_length = 0\n",
    )

    # When loading the config
    cfg = _load_config_mod(hooks_dir).load_config(home=home, project_dir=str(proj))

    # Then each option reads back with its own type and the project value wins
    assert cfg.option("commit-message", "max_subject_length", default=100) == 0
    assert cfg.option("commit-message", "force_imperative", default=False) is True
    assert cfg.option("commit-message", "types", default=("x",)) == ("feat", "fix")


def test_hook_option_mistyped_value_falls_back(
    hooks_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Verify a value whose type differs from the default yields the default with a warning."""
    # Given a bool where an int is expected and an int where a bool is expected
    home = tmp_path / "home"
    _write(
        home / ".claude" / "natelandau-toolkit.toml",
        "[hooks.commit-message]\nmax_subject_length = true\nforce_imperative = 1\n",
    )

    # When reading them with typed defaults
    cfg = _load_config_mod(hooks_dir).load_config(home=home, project_dir=str(tmp_path / "proj"))

    # Then bool and int are not confused and each falls back to its default
    assert cfg.option("commit-message", "max_subject_length", default=100) == 100
    assert cfg.option("commit-message", "force_imperative", default=False) is False
    assert "max_subject_length must be int" in capsys.readouterr().err


def test_hook_option_unsupported_shape_dropped(
    hooks_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Verify a table or mixed-type list option is dropped at load with a warning."""
    # Given a list holding a non-string and a nested table
    home = tmp_path / "home"
    _write(
        home / ".claude" / "natelandau-toolkit.toml",
        '[hooks.commit-message]\ntypes = ["feat", 1]\nnested = { a = "b" }\n',
    )

    # When loading the config
    cfg = _load_config_mod(hooks_dir).load_config(home=home, project_dir=str(tmp_path / "proj"))

    # Then neither value is kept
    assert cfg.hook_options["commit-message"] == {}
    assert "ignoring [hooks.commit-message] types" in capsys.readouterr().err


def test_additive_option_unions_across_layers(hooks_dir: Path, tmp_path: Path) -> None:
    """Verify an additive option keeps global entries and appends project ones."""
    # Given global and project layers that each protect branches
    home = tmp_path / "home"
    proj = tmp_path / "proj"
    _write(
        home / ".claude" / "natelandau-toolkit.toml",
        '[hooks.branch-protection]\nprotected_branches = ["develop", "release/*"]\n',
    )
    _write(
        proj / ".claude" / "natelandau-toolkit.toml",
        '[hooks.branch-protection]\nprotected_branches = ["staging", "develop"]\n',
    )

    # When loading the config
    cfg = _load_config_mod(hooks_dir).load_config(home=home, project_dir=str(proj))

    # Then the lists are unioned, in order, without duplicates
    assert cfg.option("branch-protection", "protected_branches", default=()) == (
        "develop",
        "release/*",
        "staging",
    )


def test_additive_option_not_cleared_by_an_empty_project_list(
    hooks_dir: Path, tmp_path: Path
) -> None:
    """Verify an empty project list leaves an additive global list intact."""
    # Given a global list and an empty project list
    home = tmp_path / "home"
    proj = tmp_path / "proj"
    _write(
        home / ".claude" / "natelandau-toolkit.toml",
        '[hooks.branch-protection]\nprotected_branches = ["develop"]\n',
    )
    _write(
        proj / ".claude" / "natelandau-toolkit.toml",
        "[hooks.branch-protection]\nprotected_branches = []\n",
    )

    # When loading the config
    cfg = _load_config_mod(hooks_dir).load_config(home=home, project_dir=str(proj))

    # Then the global entry survives
    assert cfg.option("branch-protection", "protected_branches", default=()) == ("develop",)


def test_additive_option_not_cleared_by_a_project_scalar(hooks_dir: Path, tmp_path: Path) -> None:
    """Verify a scalar in the project layer cannot replace an additive global list."""
    # Given a global list and a project scalar for the same additive option
    home = tmp_path / "home"
    proj = tmp_path / "proj"
    _write(
        home / ".claude" / "natelandau-toolkit.toml",
        '[hooks.branch-protection]\nprotected_branches = ["develop"]\n',
    )
    _write(
        proj / ".claude" / "natelandau-toolkit.toml",
        '[hooks.branch-protection]\nprotected_branches = "none"\n',
    )

    # When loading the config
    cfg = _load_config_mod(hooks_dir).load_config(home=home, project_dir=str(proj))

    # Then the global entry survives
    assert cfg.option("branch-protection", "protected_branches", default=()) == ("develop",)


def test_non_additive_list_option_replaced_by_project(hooks_dir: Path, tmp_path: Path) -> None:
    """Verify a list option outside ADDITIVE_OPTIONS is still replaced, not unioned."""
    # Given global and project lists for a style option
    home = tmp_path / "home"
    proj = tmp_path / "proj"
    _write(
        home / ".claude" / "natelandau-toolkit.toml",
        '[hooks.commit-message]\ntypes = ["feat", "fix"]\n',
    )
    _write(
        proj / ".claude" / "natelandau-toolkit.toml", '[hooks.commit-message]\ntypes = ["docs"]\n'
    )

    # When loading the config
    cfg = _load_config_mod(hooks_dir).load_config(home=home, project_dir=str(proj))

    # Then the project list wins outright
    assert cfg.option("commit-message", "types", default=()) == ("docs",)
