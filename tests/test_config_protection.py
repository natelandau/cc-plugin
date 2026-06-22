"""Characterization tests for config_protection.py.

Each case materializes a real file under tmp_path (the hook inspects the
filesystem: lstat for existence, on-disk content for pyproject diffing),
builds an Edit/Write payload pointing at it, and pipes that through the
hook as a subprocess. exit 0 = allow, exit 2 = block.

A protected file existing on disk means a *modification* (blocked); the
file absent means *creation* (allowed). For pyproject.toml the case
supplies `existing` content plus either an Edit substitution or a Write
`content`, exercising the table-level diff.
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from pathlib import Path

RUFF_TOML = '[lint]\nselect = ["E"]\n'
PYPROJECT_BASE = """\
[project]
name = "demo"
version = "0.1.0"
dependencies = ["requests"]

[tool.ruff]
line-length = 100

[tool.ruff.lint]
select = ["E", "F"]

[tool.pytest.ini_options]
addopts = "-x"
"""


@dataclass(frozen=True)
class Case:
    """One config_protection case.

    `filename` is created under tmp_path. `existing` is its pre-written
    content (None = the file is absent, i.e. a creation). For Edit set
    `old_string`/`new_string`; for Write set `content`.
    """

    id: str
    tool_name: str
    filename: str
    existing: str | None
    expect_exit: int
    content: str = ""
    old_string: str = ""
    new_string: str = ""
    replace_all: bool = False
    stderr_contains: tuple[str, ...] = field(default_factory=tuple)


CASES: tuple[Case, ...] = (
    # --- whole-file configs: modification blocked, creation allowed ---
    Case(
        id="edit existing ruff.toml blocked",
        tool_name="Edit",
        filename="ruff.toml",
        existing=RUFF_TOML,
        old_string='select = ["E"]',
        new_string="select = []",
        expect_exit=2,
        stderr_contains=("BLOCKED", "config-protection", "ruff.toml"),
    ),
    Case(
        id="write existing pre-commit config blocked",
        tool_name="Write",
        filename=".pre-commit-config.yaml",
        existing="repos: []\n",
        content="repos: []\n# weakened\n",
        expect_exit=2,
        stderr_contains=("config-protection", ".pre-commit-config.yaml"),
    ),
    Case(
        id="create new ruff.toml allowed",
        tool_name="Write",
        filename="ruff.toml",
        existing=None,
        content=RUFF_TOML,
        expect_exit=0,
    ),
    Case(
        id="write existing mypy.ini blocked",
        tool_name="Write",
        filename="mypy.ini",
        existing="[mypy]\nstrict = true\n",
        content="[mypy]\nstrict = false\n",
        expect_exit=2,
        stderr_contains=("mypy.ini",),
    ),
    Case(
        id="edit existing yamllint blocked",
        tool_name="Edit",
        filename=".yamllint.yml",
        existing="rules:\n  line-length: enable\n",
        old_string="enable",
        new_string="disable",
        expect_exit=2,
        stderr_contains=(".yamllint.yml",),
    ),
    # --- non-config files pass through ---
    Case(
        id="edit main.py allowed",
        tool_name="Edit",
        filename="main.py",
        existing="x = 1\n",
        old_string="x = 1",
        new_string="x = 2",
        expect_exit=0,
    ),
    # --- pyproject.toml: protected tables blocked, rest allowed ---
    Case(
        id="edit pyproject tool.ruff line-length blocked",
        tool_name="Edit",
        filename="pyproject.toml",
        existing=PYPROJECT_BASE,
        old_string="line-length = 100",
        new_string="line-length = 200",
        expect_exit=2,
        stderr_contains=("config-protection", "[tool.ruff]", "pyproject.toml"),
    ),
    Case(
        id="edit pyproject nested tool.ruff.lint blocked",
        tool_name="Edit",
        filename="pyproject.toml",
        existing=PYPROJECT_BASE,
        old_string='select = ["E", "F"]',
        new_string='select = ["E"]',
        expect_exit=2,
        stderr_contains=("[tool.ruff]",),
    ),
    Case(
        id="edit pyproject dependencies allowed",
        tool_name="Edit",
        filename="pyproject.toml",
        existing=PYPROJECT_BASE,
        old_string='dependencies = ["requests"]',
        new_string='dependencies = ["requests", "httpx"]',
        expect_exit=0,
    ),
    Case(
        id="edit pyproject project metadata allowed",
        tool_name="Edit",
        filename="pyproject.toml",
        existing=PYPROJECT_BASE,
        old_string='version = "0.1.0"',
        new_string='version = "0.2.0"',
        expect_exit=0,
    ),
    Case(
        id="edit pyproject pytest config allowed",
        tool_name="Edit",
        filename="pyproject.toml",
        existing=PYPROJECT_BASE,
        old_string='addopts = "-x"',
        new_string='addopts = "-x --tb=short"',
        expect_exit=0,
    ),
    Case(
        id="write pyproject changing tool.ruff blocked",
        tool_name="Write",
        filename="pyproject.toml",
        existing=PYPROJECT_BASE,
        content=PYPROJECT_BASE.replace("line-length = 100", "line-length = 250"),
        expect_exit=2,
        stderr_contains=("[tool.ruff]",),
    ),
    Case(
        id="write pyproject changing only deps allowed",
        tool_name="Write",
        filename="pyproject.toml",
        existing=PYPROJECT_BASE,
        content=PYPROJECT_BASE.replace('["requests"]', '["requests", "httpx"]'),
        expect_exit=0,
    ),
    Case(
        id="adding new tool.mypy table to pyproject allowed (bootstrap)",
        tool_name="Edit",
        filename="pyproject.toml",
        existing=PYPROJECT_BASE,
        old_string='addopts = "-x"',
        new_string='addopts = "-x"\n\n[tool.mypy]\nstrict = true',
        expect_exit=0,
    ),
    Case(
        id="creating pyproject from scratch allowed",
        tool_name="Write",
        filename="pyproject.toml",
        existing=None,
        content=PYPROJECT_BASE,
        expect_exit=0,
    ),
    Case(
        id="edit with unlocatable old_string passes through",
        tool_name="Edit",
        filename="pyproject.toml",
        existing=PYPROJECT_BASE,
        old_string="this text is not in the file",
        new_string="anything",
        expect_exit=0,
    ),
    # --- non-applicable tools / missing fields pass through ---
    Case(
        id="Read tool ignored",
        tool_name="Read",
        filename="ruff.toml",
        existing=RUFF_TOML,
        expect_exit=0,
    ),
)


def _payload(case: Case, target: Path) -> dict[str, Any]:
    """Build the hook payload for a case against a materialized target path."""
    if case.tool_name == "Write":
        tool_input: dict[str, Any] = {"file_path": str(target), "content": case.content}
    elif case.tool_name == "Edit":
        tool_input = {
            "file_path": str(target),
            "old_string": case.old_string,
            "new_string": case.new_string,
            "replace_all": case.replace_all,
        }
    else:
        tool_input = {"file_path": str(target)}
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": case.tool_name,
        "tool_input": tool_input,
    }


@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_config_protection(case: Case, hooks_dir: Path, tmp_path: Path) -> None:
    """Verify the hook blocks config-weakening edits and allows the rest."""
    # Given a materialized target file (present = modification, absent = creation)
    hook = hooks_dir / "config_protection.py"
    target = tmp_path / case.filename
    if case.existing is not None:
        target.write_text(case.existing, encoding="utf-8")

    # When invoking the hook with the Edit/Write payload on stdin
    proc = subprocess.run(
        [str(hook)],
        input=json.dumps(_payload(case, target)),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    # Then exit code and stderr content match expectations
    diag = f"\n  stderr={proc.stderr!r}\n  stdout={proc.stdout!r}"
    assert proc.returncode == case.expect_exit, f"exit={proc.returncode}{diag}"
    for s in case.stderr_contains:
        assert s in proc.stderr, f"missing {s!r} in stderr{diag}"


def test_config_protection_via_dispatcher(hooks_dir: Path, tmp_path: Path) -> None:
    """Verify the consolidated dispatcher routes Edit to config-protection and blocks."""
    # Given an existing ruff.toml and a project config selecting the standard profile
    dispatcher = hooks_dir / "pre_tool_dispatcher.py"
    target = tmp_path / "ruff.toml"
    target.write_text(RUFF_TOML, encoding="utf-8")
    proj = tmp_path / "proj"
    cfgfile = proj / ".claude" / "natelandau-toolkit.toml"
    cfgfile.parent.mkdir(parents=True, exist_ok=True)
    cfgfile.write_text('profile = "standard"\ndisabled_hooks = []\n', encoding="utf-8")
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(proj)
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(target),
            "old_string": 'select = ["E"]',
            "new_string": "select = []",
        },
    }

    # When the dispatcher processes the payload
    proc = subprocess.run(
        [str(dispatcher)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
        env=env,
    )

    # Then it blocks with the config-protection reason
    assert proc.returncode == 2, f"exit={proc.returncode}\n  stderr={proc.stderr!r}"
    assert "config-protection" in proc.stderr


def test_config_protection_disabled_via_config(hooks_dir: Path, tmp_path: Path) -> None:
    """Verify disabling config-protection lets the dispatcher allow the edit."""
    # Given an existing ruff.toml and a project config disabling the hook
    dispatcher = hooks_dir / "pre_tool_dispatcher.py"
    target = tmp_path / "ruff.toml"
    target.write_text(RUFF_TOML, encoding="utf-8")
    proj = tmp_path / "proj"
    cfgfile = proj / ".claude" / "natelandau-toolkit.toml"
    cfgfile.parent.mkdir(parents=True, exist_ok=True)
    cfgfile.write_text('disabled_hooks = ["config-protection"]\n', encoding="utf-8")
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(proj)
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(target),
            "old_string": 'select = ["E"]',
            "new_string": "select = []",
        },
    }

    # When the dispatcher processes the payload
    proc = subprocess.run(
        [str(dispatcher)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
        env=env,
    )

    # Then the edit is allowed
    assert proc.returncode == 0, f"exit={proc.returncode}\n  stderr={proc.stderr!r}"


@pytest.fixture
def configprot_module(hooks_dir: Path) -> Any:
    """Import config_protection with the hooks dir importable."""
    sys.path.insert(0, str(hooks_dir))
    try:
        yield importlib.import_module("config_protection")
    finally:
        sys.path.pop(0)


def _cfg(project_dir: str | None = None) -> Any:
    from lib.config import Config  # ty: ignore[unresolved-import]

    return Config(
        profile="standard", disabled_hooks=frozenset(), hook_options={}, project_dir=project_dir
    )


def _project_configprot(tmp_path: Path, content: str) -> str:
    """Write a config_protection project rules file; return the project dir."""
    d = tmp_path / ".claude" / "natelandau-toolkit"
    d.mkdir(parents=True, exist_ok=True)
    (d / "config_protection.rules.toml").write_text(content, encoding="utf-8")
    return str(tmp_path)


def test_project_protected_file_blocked(configprot_module: Any, tmp_path: Path) -> None:
    """Verify a project-listed config file is protected when modified."""
    # Given a project rules file adding webpack.config.js (note: omits the
    # pyproject-tables array on purpose, to prove a single-list file is valid)
    proj = _project_configprot(tmp_path, 'protected_files = ["webpack.config.js"]\n')
    # Given that file exists on disk (modification, not creation)
    target = tmp_path / "src" / "webpack.config.js"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("module.exports = {}\n", encoding="utf-8")
    payload = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(target),
            "old_string": "{}",
            "new_string": "{ mode: 'none' }",
        },
    }
    # When evaluating the edit with the project dir set
    decision = configprot_module.evaluate(payload, _cfg(project_dir=proj))
    # Then it is blocked by config-protection
    assert decision is not None
    assert decision.block
    assert "webpack.config.js" in decision.reason


def test_no_project_file_leaves_builtins_intact(configprot_module: Any, tmp_path: Path) -> None:
    """Verify built-in config protection is unchanged with no project file."""
    # Given a project dir with no rules file and an existing ruff.toml
    target = tmp_path / "ruff.toml"
    target.write_text(RUFF_TOML, encoding="utf-8")
    payload = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(target),
            "old_string": 'select = ["E"]',
            "new_string": "select = []",
        },
    }
    # When evaluating the edit
    decision = configprot_module.evaluate(payload, _cfg(project_dir=str(tmp_path)))
    # Then the built-in still blocks ruff.toml
    assert decision is not None
    assert decision.block
    assert "ruff.toml" in decision.reason


def test_malformed_project_file_keeps_builtins(configprot_module: Any, tmp_path: Path) -> None:
    """Verify a malformed project file is ignored but built-ins still fire."""
    # Given a malformed project rules file and an existing ruff.toml
    proj = _project_configprot(tmp_path, "protected_files = = nope\n")
    target = tmp_path / "ruff.toml"
    target.write_text(RUFF_TOML, encoding="utf-8")
    payload = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(target),
            "old_string": 'select = ["E"]',
            "new_string": "select = []",
        },
    }
    # When evaluating the edit
    decision = configprot_module.evaluate(payload, _cfg(project_dir=proj))
    # Then the built-in still blocks ruff.toml despite the broken project file
    assert decision is not None
    assert decision.block
    assert "ruff.toml" in decision.reason
