"""Characterization tests for use_uv.py.

Pipes representative bash payloads through the hook (as a subprocess) and
asserts on the stdout JSON payload. The hook always exits 0; a nudge is
expressed as a `hookSpecificOutput.additionalContext` JSON object on stdout,
and an "allow silently" decision is expressed as no stdout at all.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    import subprocess
    from collections.abc import Callable
    from pathlib import Path
    from types import ModuleType


def _bash(cmd: str) -> dict[str, Any]:
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": cmd},
    }


@dataclass(frozen=True)
class Case:
    """One use_uv test case.

    A non-empty `context_contains` means the hook should emit a JSON payload
    on stdout whose `hookSpecificOutput.additionalContext` field includes
    every listed substring. An empty tuple means the hook should stay silent
    (no stdout). The hook always exits 0.
    """

    id: str
    payload: dict[str, Any]
    context_contains: tuple[str, ...] = ()


CASES: tuple[Case, ...] = (
    # Non-bash tools pass straight through.
    Case(
        id="non-bash tool ignored",
        payload={"tool_name": "Edit", "tool_input": {"file_path": "x.py"}},
    ),
    # The reported bug: `uv run pytest` was substring-matched as `pytest`.
    Case(
        id="uv run pytest allowed",
        payload=_bash("uv run pytest"),
    ),
    Case(
        id="uv run pytest with flags allowed",
        payload=_bash("uv run pytest --collect-only -q"),
    ),
    Case(
        id="uv run ruff check allowed",
        payload=_bash("uv run ruff check src/"),
    ),
    Case(
        id="uv run python allowed",
        payload=_bash("uv run python script.py"),
    ),
    Case(
        id="uv add allowed",
        payload=_bash("uv add httpx"),
    ),
    # Bare invocations still nudge.
    Case(
        id="bare pytest nudges",
        payload=_bash("pytest -v"),
        context_contains=("pytest", "uv run pytest"),
    ),
    Case(
        id="bare ruff nudges",
        payload=_bash("ruff check src/"),
        context_contains=("ruff", "uv run ruff"),
    ),
    Case(
        id="bare python nudges",
        payload=_bash("python script.py"),
        context_contains=("python", "uv run python"),
    ),
    Case(
        id="bare pip install nudges",
        payload=_bash("pip install httpx"),
        context_contains=("pip install", "uv add"),
    ),
    # Verb-sensitive: pip without `install` should not nudge.
    Case(
        id="pip --version allowed",
        payload=_bash("pip --version"),
    ),
    # Token boundaries: the tool name appearing inside an unrelated word
    # or string literal should not trigger.
    Case(
        id="echo mentioning pytest allowed",
        payload=_bash("echo 'remember to run pytest later'"),
    ),
    Case(
        id="path containing python allowed",
        payload=_bash("ls /usr/lib/python3.12"),
    ),
    # Compound clauses: each clause is checked independently.
    Case(
        id="cd then bare pytest nudges",
        payload=_bash("cd src && pytest"),
        context_contains=("pytest",),
    ),
    Case(
        id="uv run pytest piped to head allowed",
        payload=_bash("uv run pytest | head -20"),
    ),
    Case(
        id="bare pytest piped to head nudges",
        payload=_bash("pytest | head -20"),
        context_contains=("pytest",),
    ),
    # Env-var prefix should not hide a bare invocation.
    Case(
        id="env-prefixed bare pytest nudges",
        payload=_bash("PYTHONPATH=src pytest"),
        context_contains=("pytest",),
    ),
    # Absolute path to the interpreter still gets nudged via basename.
    Case(
        id="absolute python path nudges",
        payload=_bash("/usr/bin/python script.py"),
        context_contains=("python",),
    ),
)


@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_use_uv(
    case: Case, run_pretooluse: Callable[[dict[str, Any]], subprocess.CompletedProcess[str]]
) -> None:
    """Verify the hook nudges or stays silent per its rules."""
    # When invoking the hook with the payload on stdin
    proc = run_pretooluse(case.payload)

    # Then the hook always exits 0; the difference between nudge and silent
    # is on stdout.
    diag = f"\n  stdout={proc.stdout!r}\n  stderr={proc.stderr!r}"
    assert proc.returncode == 0, f"exit={proc.returncode}{diag}"

    if not case.context_contains:
        assert proc.stdout == "", f"expected silent stdout{diag}"
        return

    payload = json.loads(proc.stdout)
    hook_output = payload["hookSpecificOutput"]
    assert hook_output["hookEventName"] == "PreToolUse", diag
    context = hook_output["additionalContext"]
    for s in case.context_contains:
        assert s in context, f"missing {s!r} in additionalContext{diag}"


def _load_use_uv(hooks_dir: Path) -> ModuleType:
    """Import pretooluse/use_uv.py in-process with the hooks dir on sys.path."""
    sys.path.insert(0, str(hooks_dir))
    try:
        spec = importlib.util.spec_from_file_location(
            "_use_uv_under_test", hooks_dir / "pretooluse" / "use_uv.py"
        )
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


def test_use_uv_debounce_suppresses_second_dispatch(
    run_pretooluse: Callable[[dict[str, Any]], subprocess.CompletedProcess[str]],
) -> None:
    """Verify the second dispatch of one nudge in a session emits no stdout."""
    # Given a flagged command carrying a session_id (run_pretooluse isolates the
    # state bridge to a per-test tmp dir, shared across both calls)
    payload = {**_bash("pytest -v"), "session_id": "wire-1"}

    # When the same payload is piped through the dispatcher twice
    first = run_pretooluse(payload)
    second = run_pretooluse(payload)

    # Then the first nudges on stdout and the second is suppressed (silent)
    assert first.returncode == 0
    assert "uv run pytest" in first.stdout
    assert second.returncode == 0
    assert second.stdout == "", f"expected suppressed stdout, got {second.stdout!r}"


def test_use_uv_debounces_per_session(
    hooks_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify a nudge fires once per session, per tool, and always without a session id."""
    # Given the state bridge isolated to a tmp root and a loaded hook
    monkeypatch.setenv("NATELANDAU_TOOLKIT_STATE_DIR", str(tmp_path))
    use_uv = _load_use_uv(hooks_dir)
    event = {"tool_name": "Bash", "tool_input": {"command": "pytest -v"}, "session_id": "s1"}

    # When the same nudge is evaluated twice in one session
    first = use_uv.evaluate(dict(event), None)
    second = use_uv.evaluate(dict(event), None)

    # Then it fires once and is suppressed the second time
    assert first is not None
    assert first.block is False
    assert second is None

    # And a distinct tool in the same session still fires
    ruff_event = {**event, "tool_input": {"command": "ruff check src/"}}
    assert use_uv.evaluate(ruff_event, None) is not None

    # And the same nudge in a different session fires again (per-session debounce)
    assert use_uv.evaluate({**event, "session_id": "s2"}, None) is not None

    # And without a session id to key on, the nudge always fires
    no_session = {"tool_name": "Bash", "tool_input": {"command": "pytest -v"}}
    assert use_uv.evaluate(dict(no_session), None) is not None
    assert use_uv.evaluate(dict(no_session), None) is not None
