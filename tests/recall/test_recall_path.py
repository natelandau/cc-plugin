"""Verify the recall-path.py facade prints the store paths it shares with Store."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from recall.store import Store  # ty: ignore[unresolved-import]

from tests._env import clean_environ

RESOLVER = (
    Path(__file__).resolve().parent.parent.parent
    / "plugins"
    / "natelandau-recall"
    / "hooks"
    / "recall-path.py"
)


def _run(
    flag: str, *, cwd: Path, env_overrides: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(RESOLVER), flag],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env={**clean_environ(), **env_overrides},
        check=False,
        timeout=30,
    )


@pytest.mark.parametrize(
    ("flag", "attr"),
    [
        ("--data-dir", "data_dir"),
        ("--handoff", "handoff_path"),
        ("--backlog", "backlog_path"),
        ("--learnings", "learnings_dir"),
    ],
)
def test_resolver_prints_store_path(flag: str, attr: str, tmp_path: Path) -> None:
    """Verify each flag prints the path of the matching Store accessor."""
    # Given an isolated non-git project
    proj = tmp_path / "proj"
    proj.mkdir()
    env = {"XDG_DATA_HOME": str(tmp_path / "data"), "CLAUDE_PROJECT_DIR": str(proj)}
    expected = getattr(Store.for_cwd(cwd=proj, env={**clean_environ(), **env}), attr)

    # When the resolver runs in that project
    proc = _run(flag, cwd=proj, env_overrides=env)

    # Then it prints the same path the engine would compute
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == str(expected)


def test_resolver_no_flag_is_usage_error(tmp_path: Path) -> None:
    """Verify invoking with no target flag exits non-zero (a usage error)."""
    # Given an isolated project
    proj = tmp_path / "proj"
    proj.mkdir()
    # When the resolver runs with no flag
    proc = subprocess.run(
        [str(RESOLVER)],
        cwd=str(proj),
        capture_output=True,
        text=True,
        env={**clean_environ(), "CLAUDE_PROJECT_DIR": str(proj)},
        check=False,
        timeout=30,
    )
    # Then it is a usage error
    assert proc.returncode != 0
    assert proc.stdout.strip() == ""


def test_resolver_unknown_flag_is_usage_error(tmp_path: Path) -> None:
    """Verify an unknown flag exits non-zero rather than printing a path."""
    # Given an isolated project
    proj = tmp_path / "proj"
    proj.mkdir()
    # When the resolver runs with an unknown flag
    proc = _run("--nope", cwd=proj, env_overrides={"CLAUDE_PROJECT_DIR": str(proj)})
    # Then it is a usage error
    assert proc.returncode != 0
    assert proc.stdout.strip() == ""
