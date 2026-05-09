#!/usr/bin/env -S uv run --script

# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///

"""PreToolUse hook: gate `gh pr create` behind a configurable list of pre-PR checks.

Each check is one of:

- Deterministic (`verify_cmd` set): the hook runs the shell command in the
  session cwd. Exit 0 means the check passes; any other exit blocks the PR
  with the check's `instruction` and the verifier output.
- Trust-based (`verify_cmd` is None): the hook blocks once per session with
  the `instruction`, marks the check shown, and on the next `gh pr create`
  it assumes the assistant complied. Use this for judgment-based asks like
  "/simplify" that have no deterministic gate.

To customize, edit the `CHECKS` tuple below. For tests or per-project
overrides, set `PR_CHECKS_CONFIG` to a JSON file with the same shape.
Session state (which trust-based checks have been shown) lives at
`$TMPDIR/pr-checks-<hash>.json` and is cleared once every check passes.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

GH_PR_CREATE = re.compile(r"(^|[\s;|&])gh\s+pr\s+create(\s|$)")


@dataclass(frozen=True, slots=True)
class Check:
    """One pre-PR gate evaluated before `gh pr create` is allowed.

    A check with a `verify_cmd` is deterministic and re-runs every retry.
    A check without one is trust-based and only blocks the first retry it
    sees in a given session, so the assistant sees the instruction once
    and is presumed to have complied on the next attempt.
    """

    id: str
    instruction: str
    verify_cmd: str | None = None


# === CHECK DEFINITIONS ===
#
# Append a Check(...) to CHECKS to add a gate. Order matters: the first
# failing check blocks and later checks are not evaluated until it passes.

CHECKS: tuple[Check, ...] = (
    Check(
        id="simplify",
        instruction=(
            "Run /simplify on the changed code before opening the PR. "
            "Review the suggestions and apply any that improve reuse, "
            "quality, or efficiency."
        ),
    ),
    Check(
        id="conventional-commits",
        instruction=(
            "One or more commits on this branch don't follow Conventional "
            "Commits. Rewrite them via `git rebase -i` (or `git commit "
            "--amend` for the latest). Format: `<type>(<scope>): <subject>`, "
            "type one of build|ci|docs|feat|fix|perf|refactor|style|test, "
            "lowercase subject, no trailing period, max 70 chars."
        ),
        # Print every subject not matching the conventional-commits pattern.
        # The verifier passes (exit 0) only when no offending subjects exist.
        verify_cmd=(
            "subjects=$(git log origin/main..HEAD --pretty=format:'%s' 2>/dev/null); "
            '[ -z "$subjects" ] && exit 0; '
            "bad=$(printf '%s\\n' \"$subjects\" "
            "| grep -vE '^(build|ci|docs|feat|fix|perf|refactor|style|test)(\\([^)]+\\))?: .{1,68}[^.]$' "
            "|| true); "
            '[ -z "$bad" ] || { echo "Non-conforming commits:"; echo "$bad"; exit 1; }'
        ),
    ),
)


def main() -> None:
    """Entry point for the PreToolUse hook."""
    try:
        payload: dict[str, Any] = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    if payload.get("tool_name") != "Bash":
        sys.exit(0)

    command: str = payload.get("tool_input", {}).get("command", "")
    if not GH_PR_CREATE.search(command):
        sys.exit(0)

    checks = load_checks()
    if not checks:
        sys.exit(0)

    cwd: str = payload.get("cwd") or str(Path.cwd())
    state_path = state_file_for(payload)
    state = load_state(state_path)
    shown: set[str] = set(state.get("shown", []))

    for check in checks:
        if check.verify_cmd is not None:
            ok, detail = run_verifier(check.verify_cmd, cwd=cwd)
            if ok:
                continue
            block(check, detail=detail)

        # Trust-based: prompt once per session, assume compliance on retry.
        if check.id in shown:
            continue
        shown.add(check.id)
        save_state(state_path, {"shown": sorted(shown)})
        block(check)

    # All checks passed; clear session state so a follow-up PR starts fresh.
    state_path.unlink(missing_ok=True)
    sys.exit(0)


def load_checks() -> tuple[Check, ...]:
    """Return CHECKS, or an override loaded from PR_CHECKS_CONFIG.

    The override exists for tests and per-project customization. Production
    use should edit the inline CHECKS tuple instead so the source of truth
    stays in version control with the hook.
    """
    override = os.environ.get("PR_CHECKS_CONFIG")
    if not override:
        return CHECKS

    raw = Path(override).read_text()
    data = json.loads(raw)
    return tuple(
        Check(
            id=item["id"],
            instruction=item["instruction"],
            verify_cmd=item.get("verify_cmd"),
        )
        for item in data.get("checks", [])
    )


def run_verifier(cmd: str, *, cwd: str) -> tuple[bool, str]:
    """Run a verifier shell command, return (passed, combined_output).

    Exit 0 is treated as pass. Any other exit (including signal kills and
    spawn failures) is treated as fail and the combined stdout/stderr is
    returned to be surfaced to the assistant.
    """
    try:
        result = subprocess.run(  # noqa: S602
            cmd,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=55,
            check=False,
        )
    except (subprocess.SubprocessError, FileNotFoundError) as exc:
        return False, f"verifier failed to execute: {exc}"
    detail = (result.stdout + result.stderr).strip()
    return result.returncode == 0, detail


def block(check: Check, *, detail: str = "") -> None:
    """Print a block message to stderr and exit 2."""
    msg = f"PR-CHECK BLOCKED [{check.id}]\n\n{check.instruction}"
    if detail:
        msg += f"\n\nVerifier output:\n{detail}"
    if check.verify_cmd is None:
        msg += "\n\nWhen done, retry the `gh pr create` command."
    print(msg, file=sys.stderr)  # noqa: T201
    sys.exit(2)


def state_file_for(payload: dict[str, Any]) -> Path:
    """Pick a session-scoped path under tempfile.gettempdir() for shown-state."""
    key = payload.get("session_id") or payload.get("transcript_path") or ""
    digest = hashlib.sha256(key.encode()).hexdigest()[:16]
    return Path(tempfile.gettempdir()) / f"pr-checks-{digest}.json"


def load_state(path: Path) -> dict[str, Any]:
    """Read the session state JSON, returning {} if missing or malformed."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save_state(path: Path, state: dict[str, Any]) -> None:
    """Write session state atomically enough for our single-writer use case."""
    path.write_text(json.dumps(state))


if __name__ == "__main__":
    main()
