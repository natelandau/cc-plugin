"""Characterization tests for use_uv.py.

Pipes representative bash payloads through the hook (as a subprocess) and
asserts on the stdout JSON payload. The hook always exits 0; a nudge is
expressed as a `hookSpecificOutput.additionalContext` JSON object on stdout,
and an "allow silently" decision is expressed as no stdout at all.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from pathlib import Path


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
def test_use_uv(case: Case, hooks_dir: Path) -> None:
    """Verify the hook nudges or stays silent per its rules."""
    # Given a hook script and a payload
    hook = hooks_dir / "use_uv.py"

    # When invoking the hook with the payload on stdin
    proc = subprocess.run(
        [str(hook)],
        input=json.dumps(case.payload),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

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
