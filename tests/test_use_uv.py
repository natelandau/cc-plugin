"""Characterization tests for use_uv.py.

Pipes representative bash payloads through the hook (as a subprocess) and
asserts on the stdout JSON payload. The hook always exits 0; a nudge is
expressed as a `hookSpecificOutput.additionalContext` JSON object on stdout,
and an "allow silently" decision is expressed as no stdout at all.

The nudge is gated on the project's own virtualenv: a bare tool name is only
flagged when `.venv/bin/<tool>` exists at or above the payload's cwd. Tests
therefore run against a fake project layout whose venv provides `python` and
`pytest` but not `ruff`, so `ruff` stands in for a tool that lives on PATH.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pytest

from tests._helpers import bash_payload as _bash
from tests._helpers import load_hook_module

if TYPE_CHECKING:
    import subprocess
    from collections.abc import Callable, Mapping
    from pathlib import Path
    from types import ModuleType


@pytest.fixture(scope="session")
def uv_dirs(tmp_path_factory: pytest.TempPathFactory) -> Mapping[str, str]:
    """Provide a fake uv project (venv with python + pytest, no ruff) and a bare dir.

    Session-scoped because the hook only reads the layout.
    """
    root = tmp_path_factory.mktemp("uv_dirs")
    proj = root / "proj"
    venv_bin = proj / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    (proj / ".venv" / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
    for tool in ("python", "pytest"):
        (venv_bin / tool).write_text("#!/bin/sh\n", encoding="utf-8")
    (proj / "src").mkdir()
    bare = root / "bare"
    bare.mkdir()
    return {"proj": str(proj), "proj/src": str(proj / "src"), "bare": str(bare)}


@dataclass(frozen=True)
class Case:
    """One use_uv test case.

    `cwd` names a key in the `uv_dirs` fixture (or None for a payload that
    carries no cwd). A non-empty `context_contains` means the hook should emit
    a JSON payload on stdout whose `hookSpecificOutput.additionalContext`
    field includes every listed substring. An empty tuple means the hook
    should stay silent (no stdout). The hook always exits 0.
    """

    id: str
    payload: dict[str, Any]
    cwd: str | None = "proj"
    context_contains: tuple[str, ...] = ()


CASES: tuple[Case, ...] = (
    # Non-bash tools pass straight through.
    Case(
        id="non-bash tool ignored",
        payload={"tool_name": "Edit", "tool_input": {"file_path": "x.py"}},
    ),
    # `uv run pytest` must not be substring-matched as `pytest`.
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
    # Bare invocations of tools the project venv provides nudge.
    Case(
        id="bare pytest nudges",
        payload=_bash("pytest -v"),
        context_contains=("pytest", "uv run pytest"),
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
    # A tool the venv does not provide resolves to the user's PATH; that is
    # the intended way to run it, so no nudge.
    Case(
        id="bare tool missing from venv allowed",
        payload=_bash("ruff check src/"),
    ),
    # Outside any uv project a bare tool is whatever is on PATH.
    Case(
        id="bare pytest outside a project allowed",
        payload=_bash("pytest -v"),
        cwd="bare",
    ),
    Case(
        id="pip install outside a project allowed",
        payload=_bash("pip install httpx"),
        cwd="bare",
    ),
    # Without a cwd there is no project to locate, so the nudge fails open to silent.
    Case(
        id="payload without cwd allowed",
        payload=_bash("pytest -v"),
        cwd=None,
    ),
    # The venv is found by walking up, so a subdirectory of the project counts.
    Case(
        id="bare pytest from project subdir nudges",
        payload=_bash("pytest -v"),
        cwd="proj/src",
        context_contains=("pytest",),
    ),
    # An explicit path is a deliberate choice of binary and is never nudged.
    Case(
        id="tilde path to user tool allowed",
        payload=_bash("~/.local/bin/ruff check src/"),
    ),
    Case(
        id="absolute python path allowed",
        payload=_bash("/usr/bin/python script.py"),
    ),
    Case(
        id="venv-relative pytest path allowed",
        payload=_bash(".venv/bin/pytest -v"),
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
    # Compound clauses: each clause is checked independently, and `cd` moves
    # the directory the venv lookup starts from.
    Case(
        id="cd within project then bare pytest nudges",
        payload=_bash("cd src && pytest"),
        context_contains=("pytest",),
    ),
    Case(
        id="cd out of project then bare pytest allowed",
        payload=_bash("cd ../bare && pytest"),
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
)


def _with_cwd(case: Case, uv_dirs: Mapping[str, str]) -> dict[str, Any]:
    """Return the case payload with its named cwd resolved to a real path."""
    if case.cwd is None:
        return case.payload
    return {**case.payload, "cwd": uv_dirs[case.cwd]}


@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_use_uv(
    case: Case,
    uv_dirs: Mapping[str, str],
    run_pretooluse: Callable[[dict[str, Any]], subprocess.CompletedProcess[str]],
) -> None:
    """Verify the hook nudges or stays silent per its rules."""
    # When invoking the hook with the payload on stdin
    proc = run_pretooluse(_with_cwd(case, uv_dirs))

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
    return load_hook_module(hooks_dir, "pretooluse/use_uv.py", "_use_uv_under_test")


def test_use_uv_debounce_suppresses_second_dispatch(
    uv_dirs: Mapping[str, str],
    run_pretooluse: Callable[[dict[str, Any]], subprocess.CompletedProcess[str]],
) -> None:
    """Verify the second dispatch of one nudge in a session emits no stdout."""
    # Given a flagged command carrying a session_id (run_pretooluse isolates the
    # state bridge to a per-test tmp dir, shared across both calls)
    payload = {**_bash("pytest -v"), "cwd": uv_dirs["proj"], "session_id": "wire-1"}

    # When the same payload is piped through the dispatcher twice
    first = run_pretooluse(payload)
    second = run_pretooluse(payload)

    # Then the first nudges on stdout and the second is suppressed (silent)
    assert first.returncode == 0
    assert "uv run pytest" in first.stdout
    assert second.returncode == 0
    assert second.stdout == "", f"expected suppressed stdout, got {second.stdout!r}"


def test_use_uv_debounces_per_session(
    hooks_dir: Path, uv_dirs: Mapping[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify a nudge fires once per session, per tool, and always without a session id."""
    # Given the state bridge isolated to a tmp root and a loaded hook
    monkeypatch.setenv("NATELANDAU_TOOLKIT_STATE_DIR", str(tmp_path))
    use_uv = _load_use_uv(hooks_dir)
    event = {**_bash("pytest -v"), "cwd": uv_dirs["proj"], "session_id": "s1"}

    # When the same nudge is evaluated twice in one session
    first = use_uv.evaluate(dict(event), None)
    second = use_uv.evaluate(dict(event), None)

    # Then it fires once and is suppressed the second time
    assert first is not None
    assert first.block is False
    assert second is None

    # And a distinct tool in the same session still fires
    python_event = {**event, "tool_input": {"command": "python script.py"}}
    assert use_uv.evaluate(python_event, None) is not None

    # And the same nudge in a different session fires again (per-session debounce)
    assert use_uv.evaluate({**event, "session_id": "s2"}, None) is not None

    # And without a session id to key on, the nudge always fires
    no_session = {**_bash("pytest -v"), "cwd": uv_dirs["proj"]}
    assert use_uv.evaluate(dict(no_session), None) is not None
    assert use_uv.evaluate(dict(no_session), None) is not None
