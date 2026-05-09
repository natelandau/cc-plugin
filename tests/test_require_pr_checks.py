"""Characterization tests for require_pr_checks.py.

Pipes representative PreToolUse payloads through the hook (as a subprocess)
with a `PR_CHECKS_CONFIG` JSON fixture overriding the inline CHECKS, plus a
TMPDIR override to isolate session state per test. Asserts on exit code,
stderr substrings, and stateful behavior across retries.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def _bash_payload(
    cmd: str,
    *,
    cwd: str,
    session_id: str = "test-session",
) -> dict[str, Any]:
    """Build a PreToolUse Bash payload with a fixed session id."""
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": cmd},
        "cwd": cwd,
        "session_id": session_id,
    }


def _write_config(path: Path, checks: list[dict[str, Any]]) -> Path:
    """Write a PR_CHECKS_CONFIG JSON file and return its path."""
    config = path / "checks.json"
    config.write_text(json.dumps({"checks": checks}))
    return config


def _run_hook(
    hook: Path,
    payload: dict[str, Any],
    *,
    config: Path,
    state_dir: Path,
) -> subprocess.CompletedProcess[str]:
    """Invoke the hook subprocess with a config override and isolated TMPDIR."""
    # Inherit the parent env so the `uv` shebang resolves; the two overrides
    # are what each test cares about.
    env = {
        **os.environ,
        "PR_CHECKS_CONFIG": str(config),
        "TMPDIR": str(state_dir),
    }
    return subprocess.run(
        [str(hook)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
        env=env,
    )


@dataclass(frozen=True)
class Case:
    """One characterization test case for the PR-checks hook.

    `make_payload` defers payload construction until `tmp_path` is available
    so cwd values can point inside the per-test scratch dir rather than a
    bare `/tmp` literal.
    """

    id: str
    checks: list[dict[str, Any]]
    make_payload: Callable[[str], dict[str, Any]]
    expect_exit: int
    stderr_contains: tuple[str, ...] = ()
    stderr_excludes: tuple[str, ...] = field(default=())


CASES: tuple[Case, ...] = (
    Case(
        id="non-bash tool passes",
        checks=[{"id": "trust", "instruction": "do thing"}],
        make_payload=lambda cwd: {
            "hook_event_name": "PreToolUse",
            "tool_name": "Edit",
            "tool_input": {"file_path": f"{cwd}/x.py"},
            "cwd": cwd,
            "session_id": "edit-session",
        },
        expect_exit=0,
    ),
    Case(
        id="bash unrelated to gh pr create passes",
        checks=[{"id": "trust", "instruction": "do thing"}],
        make_payload=lambda cwd: _bash_payload("git status", cwd=cwd),
        expect_exit=0,
    ),
    Case(
        id="gh pr list (not create) passes",
        checks=[{"id": "trust", "instruction": "do thing"}],
        make_payload=lambda cwd: _bash_payload("gh pr list", cwd=cwd),
        expect_exit=0,
    ),
    Case(
        id="empty checks list allows pr create",
        checks=[],
        make_payload=lambda cwd: _bash_payload("gh pr create --draft", cwd=cwd),
        expect_exit=0,
    ),
    Case(
        id="trust check blocks first attempt with instruction",
        checks=[{"id": "simplify", "instruction": "Run /simplify."}],
        make_payload=lambda cwd: _bash_payload("gh pr create --title x", cwd=cwd),
        expect_exit=2,
        stderr_contains=(
            "PR-CHECK BLOCKED [simplify]",
            "Run /simplify.",
            "retry the `gh pr create`",
        ),
    ),
    Case(
        id="verify_cmd success allows pr create",
        checks=[
            {
                "id": "always-pass",
                "instruction": "should not be shown",
                "verify_cmd": "true",
            }
        ],
        make_payload=lambda cwd: _bash_payload("gh pr create", cwd=cwd),
        expect_exit=0,
        stderr_excludes=("PR-CHECK BLOCKED",),
    ),
    Case(
        id="verify_cmd failure blocks with output",
        checks=[
            {
                "id": "fails",
                "instruction": "Fix the thing.",
                "verify_cmd": "echo nope >&2; exit 1",
            }
        ],
        make_payload=lambda cwd: _bash_payload("gh pr create", cwd=cwd),
        expect_exit=2,
        stderr_contains=(
            "PR-CHECK BLOCKED [fails]",
            "Fix the thing.",
            "Verifier output:",
            "nope",
        ),
    ),
    Case(
        id="env-prefixed gh pr create still detected",
        checks=[{"id": "t", "instruction": "X"}],
        make_payload=lambda cwd: _bash_payload("GH_TOKEN=abc gh pr create", cwd=cwd),
        expect_exit=2,
        stderr_contains=("PR-CHECK BLOCKED [t]",),
    ),
)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_require_pr_checks(
    case: Case,
    tmp_path: Path,
    hooks_dir: Path,
) -> None:
    """Verify the hook routes each payload to the expected exit and message."""
    # Given a config override, an isolated state dir, and the cased payload
    hook = hooks_dir / "require_pr_checks.py"
    config = _write_config(tmp_path, case.checks)
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    payload = case.make_payload(str(tmp_path))

    # When invoking the hook with the payload on stdin
    proc = _run_hook(hook, payload, config=config, state_dir=state_dir)

    # Then exit code and stderr substrings match expectations
    diag = f"\n  stderr={proc.stderr!r}\n  stdout={proc.stdout!r}"
    assert proc.returncode == case.expect_exit, f"exit={proc.returncode}{diag}"
    for s in case.stderr_contains:
        assert s in proc.stderr, f"missing {s!r} in stderr{diag}"
    for s in case.stderr_excludes:
        assert s not in proc.stderr, f"unexpected {s!r} in stderr{diag}"


def test_trust_check_skipped_on_retry_in_same_session(tmp_path: Path, hooks_dir: Path) -> None:
    """Verify a trust-based check is shown once then skipped on retry."""
    # Given a single trust-based check and an isolated state dir
    hook = hooks_dir / "require_pr_checks.py"
    config = _write_config(tmp_path, [{"id": "simplify", "instruction": "Run /simplify."}])
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    payload = _bash_payload("gh pr create", cwd=str(tmp_path), session_id="loop-session")

    # When invoking the hook twice with the same session id
    first = _run_hook(hook, payload, config=config, state_dir=state_dir)
    second = _run_hook(hook, payload, config=config, state_dir=state_dir)

    # Then the first call blocks and the second is allowed through
    assert first.returncode == 2, first.stderr
    assert "PR-CHECK BLOCKED [simplify]" in first.stderr
    assert second.returncode == 0, f"second stderr={second.stderr!r}"


def test_state_cleared_after_all_checks_pass(tmp_path: Path, hooks_dir: Path) -> None:
    """Verify the state file is removed once every check passes in a session."""
    # Given a trust check shown once and then a clean second pass
    hook = hooks_dir / "require_pr_checks.py"
    config = _write_config(tmp_path, [{"id": "trust", "instruction": "Once."}])
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    payload = _bash_payload("gh pr create", cwd=str(tmp_path), session_id="cleanup-session")

    # When the hook runs first to completion (block) then again (pass)
    blocked = _run_hook(hook, payload, config=config, state_dir=state_dir)
    passed = _run_hook(hook, payload, config=config, state_dir=state_dir)

    # Then no pr-checks state files remain in the isolated state dir
    assert blocked.returncode == 2
    assert passed.returncode == 0
    leftovers = list(state_dir.glob("pr-checks-*.json"))
    assert leftovers == [], f"state file not cleaned up: {leftovers}"


def test_separate_sessions_have_independent_state(tmp_path: Path, hooks_dir: Path) -> None:
    """Verify two sessions each see the trust block on their first attempt."""
    # Given the same trust-based check in two different sessions
    hook = hooks_dir / "require_pr_checks.py"
    config = _write_config(tmp_path, [{"id": "trust", "instruction": "Once per session."}])
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    # When each session invokes gh pr create for the first time
    session_a = _run_hook(
        hook,
        _bash_payload("gh pr create", cwd=str(tmp_path), session_id="session-a"),
        config=config,
        state_dir=state_dir,
    )
    session_b = _run_hook(
        hook,
        _bash_payload("gh pr create", cwd=str(tmp_path), session_id="session-b"),
        config=config,
        state_dir=state_dir,
    )

    # Then both sessions are blocked independently
    assert session_a.returncode == 2, session_a.stderr
    assert session_b.returncode == 2, session_b.stderr
