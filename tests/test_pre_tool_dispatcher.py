"""Integration tests for pre_tool_dispatcher.py via subprocess."""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path
    from types import ModuleType


def _run(
    hooks_dir: Path, payload: dict, project_dir: str | None = None
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    if project_dir:
        env["CLAUDE_PROJECT_DIR"] = project_dir
    else:
        env.pop("CLAUDE_PROJECT_DIR", None)
    return subprocess.run(
        [str(hooks_dir / "pre_tool_dispatcher.py")],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        env=env,
    )


def test_blocks_destructive_bash(hooks_dir: Path) -> None:
    """Verify a destructive git command is blocked with exit 2."""
    payload = {"tool_name": "Bash", "tool_input": {"command": "git push --force"}}
    proc = _run(hooks_dir, payload)
    assert proc.returncode == 2
    assert "BLOCKED" in proc.stderr


def test_advisory_passes_through_exit_0(hooks_dir: Path) -> None:
    """Verify a bare pytest yields an advisory and exit 0."""
    payload = {"tool_name": "Bash", "tool_input": {"command": "pytest -v"}}
    proc = _run(hooks_dir, payload)
    assert proc.returncode == 0
    assert "uv run pytest" in proc.stdout


def test_minimal_profile_silences_advisory(hooks_dir: Path, tmp_path: Path) -> None:
    """Verify the use-uv advisory is gated off under the minimal profile."""
    cfgfile = tmp_path / ".claude" / "natelandau-toolkit.toml"
    cfgfile.parent.mkdir(parents=True)
    cfgfile.write_text('profile = "minimal"\n', encoding="utf-8")
    payload = {"tool_name": "Bash", "tool_input": {"command": "pytest -v"}}
    proc = _run(hooks_dir, payload, project_dir=str(tmp_path))
    assert proc.returncode == 0
    assert proc.stdout == ""


def test_irrelevant_tool_is_noop(hooks_dir: Path) -> None:
    """Verify a tool with no applicable checks exits 0 silently."""
    payload = {"tool_name": "Grep", "tool_input": {"pattern": "x"}}
    proc = _run(hooks_dir, payload)
    assert proc.returncode == 0
    assert proc.stdout == ""


def test_disabled_hook_not_run(hooks_dir: Path, tmp_path: Path) -> None:
    """Verify disabling protect-system lets a strict-only system command pass."""
    cfgfile = tmp_path / ".claude" / "natelandau-toolkit.toml"
    cfgfile.parent.mkdir(parents=True)
    cfgfile.write_text('disabled_hooks = ["use-uv"]\n', encoding="utf-8")
    payload = {"tool_name": "Bash", "tool_input": {"command": "pytest -v"}}
    proc = _run(hooks_dir, payload, project_dir=str(tmp_path))
    assert proc.returncode == 0
    assert proc.stdout == ""  # use-uv disabled, nothing else advises


@pytest.fixture
def dispatcher(hooks_dir: Path) -> Generator[ModuleType]:
    """Load pre_tool_dispatcher in-process with hooks_dir on sys.path."""
    sys.path.insert(0, str(hooks_dir))
    spec = importlib.util.spec_from_file_location(
        "pre_tool_dispatcher", hooks_dir / "pre_tool_dispatcher.py"
    )
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    yield mod
    # Cleanup: remove the injected path and evict any lib.* modules so later
    # tests that also put hooks_dir on sys.path start with a clean slate.
    if str(hooks_dir) in sys.path:
        sys.path.remove(str(hooks_dir))
    for key in list(sys.modules):
        if key == "pre_tool_dispatcher" or key.startswith("lib.") or key == "lib":
            sys.modules.pop(key, None)


def test_prelude_failure_does_not_wedge(
    dispatcher: ModuleType, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify a load_config failure in the prelude exits 0 and logs to stderr."""
    # Given: read_payload succeeds but load_config raises
    err_msg = "no home"

    def _raise() -> None:
        raise RuntimeError(err_msg)

    monkeypatch.setattr(
        dispatcher,
        "read_payload",
        lambda: {"tool_name": "Bash", "tool_input": {"command": "echo hi"}},
    )
    monkeypatch.setattr(dispatcher, "load_config", _raise)

    # When: the dispatcher runs
    with pytest.raises(SystemExit) as exc_info:
        dispatcher.main()

    # Then: exit 0 (prelude failure must never wedge tool execution)
    assert exc_info.value.code == 0

    captured = capsys.readouterr()

    # Then: the failure was written to stderr with a useful message
    assert "prelude failed" in captured.err
    assert "no home" in captured.err


def test_check_exception_is_swallowed_and_loop_continues(
    dispatcher: ModuleType, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify a raising check is logged to stderr and the loop continues to the next check."""
    from lib.io import Decision  # type: ignore[import-not-found]  # ty: ignore[unresolved-import]
    from lib.registry import (  # type: ignore[import-not-found]  # ty: ignore[unresolved-import]
        Check,
    )

    # Given: a raising check followed by an advisory check
    err_msg = "boom"

    def _raise(*_args: object) -> None:
        raise RuntimeError(err_msg)

    raising_check = Check(
        id="bad-check",
        evaluate=_raise,
        tools=frozenset({"Bash"}),
    )
    advisory_check = Check(
        id="advisory-check",
        evaluate=lambda *_: Decision(block=False, context="after-error"),
        tools=frozenset({"Bash"}),
    )

    monkeypatch.setattr(dispatcher, "applicable_checks", lambda *_: [raising_check, advisory_check])
    monkeypatch.setattr(
        dispatcher,
        "read_payload",
        lambda: {"tool_name": "Bash", "tool_input": {"command": "echo hi"}},
    )

    # When: the dispatcher runs
    with pytest.raises(SystemExit) as exc_info:
        dispatcher.main()

    # Then: exit 0 (the raising check did not wedge the dispatcher)
    assert exc_info.value.code == 0

    captured = capsys.readouterr()

    # Then: the raising check's error was written to stderr
    assert "bad-check" in captured.err
    assert "boom" in captured.err

    # Then: the advisory from the following check appears on stdout
    assert "after-error" in captured.out


def test_project_rule_blocks_through_dispatcher(hooks_dir: Path, tmp_path: Path) -> None:
    """Verify a per-project protect-secrets rule blocks via the full dispatcher."""
    # Given a project rules file adding a prod-config block
    rules_dir = tmp_path / ".claude" / "natelandau-toolkit"
    rules_dir.mkdir(parents=True, exist_ok=True)
    (rules_dir / "protect_secrets.rules.toml").write_text(
        "[[rule]]\n"
        'id = "acme-prod-conf"\n'
        'level = "high"\n'
        'reason = "production secrets live in this file"\n'
        'field = "file_path"\n'
        "pattern = 'acme-prod\\.conf$'\n",
        encoding="utf-8",
    )
    payload = {"tool_name": "Read", "tool_input": {"file_path": "/repo/acme-prod.conf"}}

    # When the dispatcher processes the read with the project dir set
    proc = _run(hooks_dir, payload, project_dir=str(tmp_path))

    # Then it blocks with the project rule's reason
    assert proc.returncode == 2, f"exit={proc.returncode}\n  stderr={proc.stderr!r}"
    assert "acme-prod-conf" in proc.stderr
