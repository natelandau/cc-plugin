"""Characterization tests for confirm_recursive_rm.py.

Pipes representative bash payloads through the full PreToolUse dispatcher
(as a subprocess) and asserts on the outcome channel: exit 0 with a
permissionDecision "ask" JSON for a recursive rm outside a temp root, plain
exit 0 for everything else. Payloads are stdin data only; nothing is ever
executed.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from tests._helpers import bash_payload as _bash

if TYPE_CHECKING:
    import subprocess
    from collections.abc import Callable


def test_recursive_rm_outside_temp_asks(
    run_pretooluse: Callable[[dict[str, Any]], subprocess.CompletedProcess[str]],
) -> None:
    """Verify a recursive rm on a project path routes to the permission prompt."""
    # Given a recursive delete of an ordinary project directory
    payload = _bash("rm -rf src/generated")

    # When the PreToolUse dispatcher evaluates it
    proc = run_pretooluse(payload)

    # Then the hook asks rather than blocking or passing through
    diag = f"\n  stderr={proc.stderr!r}\n  stdout={proc.stdout!r}"
    assert proc.returncode == 0, f"exit={proc.returncode}{diag}"
    assert proc.stdout, f"expected an ask decision on stdout{diag}"
    decision = json.loads(proc.stdout)["hookSpecificOutput"]
    assert decision["permissionDecision"] == "ask", f"not an ask{diag}"
    assert "[confirm-recursive-rm]" in decision["permissionDecisionReason"], f"wrong hook{diag}"


def test_recursive_rm_under_tmp_passes_through(
    run_pretooluse: Callable[[dict[str, Any]], subprocess.CompletedProcess[str]],
) -> None:
    """Verify a recursive rm confined to /tmp never reaches the prompt."""
    # Given a recursive delete confined to a temp root
    payload = _bash("rm -rf /tmp/build-cache")

    # When the PreToolUse dispatcher evaluates it
    proc = run_pretooluse(payload)

    # Then nothing asks
    diag = f"\n  stderr={proc.stderr!r}\n  stdout={proc.stdout!r}"
    assert proc.returncode == 0, f"exit={proc.returncode}{diag}"
    assert "permissionDecision" not in proc.stdout, f"unexpected ask{diag}"


def test_chained_temp_deletes_pass_through(
    run_pretooluse: Callable[[dict[str, Any]], subprocess.CompletedProcess[str]],
) -> None:
    """Verify two chained temp deletes are judged per clause, not as one command."""
    # Given two recursive deletes, both confined to a temp root
    payload = _bash("rm -rf /tmp/a && rm -rf /tmp/b")

    # When the PreToolUse dispatcher evaluates it
    proc = run_pretooluse(payload)

    # Then nothing asks
    diag = f"\n  stderr={proc.stderr!r}\n  stdout={proc.stdout!r}"
    assert proc.returncode == 0, f"exit={proc.returncode}{diag}"
    assert "permissionDecision" not in proc.stdout, f"unexpected ask{diag}"


def test_temp_delete_chained_with_project_delete_asks(
    run_pretooluse: Callable[[dict[str, Any]], subprocess.CompletedProcess[str]],
) -> None:
    """Verify a safe first clause does not shield a project delete behind it."""
    # Given a temp delete chained ahead of a project delete
    payload = _bash("rm -rf /tmp/a && rm -rf src/generated")

    # When the PreToolUse dispatcher evaluates it
    proc = run_pretooluse(payload)

    # Then the hook asks
    diag = f"\n  stderr={proc.stderr!r}\n  stdout={proc.stdout!r}"
    assert proc.returncode == 0, f"exit={proc.returncode}{diag}"
    assert proc.stdout, f"expected an ask decision on stdout{diag}"
    decision = json.loads(proc.stdout)["hookSpecificOutput"]
    assert decision["permissionDecision"] == "ask", f"not an ask{diag}"


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf $TMPDIR/build",
        'rm -rf "${TMPDIR}/build"',
        'rm -rf "/tmp/build cache"',
        "rm -rf '/tmp/x'",
        "rm -rf /private/tmp/scratch",
    ],
    ids=["tmpdir-var", "tmpdir-braced", "quoted-with-space", "single-quoted", "private-tmp"],
)
def test_temp_root_spellings_pass_through(
    command: str,
    run_pretooluse: Callable[[dict[str, Any]], subprocess.CompletedProcess[str]],
) -> None:
    """Verify every accepted spelling of a temp root suppresses the prompt."""
    # Given a recursive delete confined to a temp root
    payload = _bash(command)

    # When the PreToolUse dispatcher evaluates it
    proc = run_pretooluse(payload)

    # Then nothing asks
    diag = f"\n  stderr={proc.stderr!r}\n  stdout={proc.stdout!r}"
    assert proc.returncode == 0, f"exit={proc.returncode}{diag}"
    assert "permissionDecision" not in proc.stdout, f"unexpected ask{diag}"


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf node_modules",
        "rm -rf .venv",
        "rm -rf __pycache__",
        "rm -rf .pytest_cache",
        "rm -rf .ruff_cache",
        "rm -rf .mypy_cache",
        "rm -rf ./node_modules",
        "rm -rf node_modules/",
        "rm -rf packages/api/node_modules",
        "rm -rf node_modules .venv",
        "rm -rf .tox",
        "rm -rf .nox",
        "rm -rf htmlcov",
        "rm -rf .ipynb_checkpoints",
    ],
    ids=[
        "node-modules",
        "venv",
        "pycache",
        "pytest-cache",
        "ruff-cache",
        "mypy-cache",
        "dot-slash",
        "trailing-slash",
        "nested",
        "two-artifacts",
        "tox",
        "nox",
        "htmlcov",
        "ipynb-checkpoints",
    ],
)
def test_regenerable_artifact_dirs_pass_through(
    command: str,
    run_pretooluse: Callable[[dict[str, Any]], subprocess.CompletedProcess[str]],
) -> None:
    """Verify a delete of a dir rebuilt from a manifest never reaches the prompt."""
    # Given a recursive delete of a regenerable artifact directory
    payload = _bash(command)

    # When the PreToolUse dispatcher evaluates it
    proc = run_pretooluse(payload)

    # Then nothing asks
    diag = f"\n  stderr={proc.stderr!r}\n  stdout={proc.stdout!r}"
    assert proc.returncode == 0, f"exit={proc.returncode}{diag}"
    assert "permissionDecision" not in proc.stdout, f"unexpected ask{diag}"


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf node_modules/../src",
        "rm -rf /tmp/../etc",
        "rm -rf .venv/../../secrets",
    ],
    ids=["artifact-escape", "temp-escape", "artifact-escape-twice"],
)
def test_traversal_out_of_an_exempt_path_asks(
    command: str,
    run_pretooluse: Callable[[dict[str, Any]], subprocess.CompletedProcess[str]],
) -> None:
    """Verify an exempt prefix cannot be used to walk back out to a real path."""
    # Given a delete whose path starts exempt but climbs out with ..
    payload = _bash(command)

    # When the PreToolUse dispatcher evaluates it
    proc = run_pretooluse(payload)

    # Then the hook asks
    diag = f"\n  stderr={proc.stderr!r}\n  stdout={proc.stdout!r}"
    assert proc.returncode == 0, f"exit={proc.returncode}{diag}"
    assert proc.stdout, f"expected an ask decision on stdout{diag}"
    decision = json.loads(proc.stdout)["hookSpecificOutput"]
    assert decision["permissionDecision"] == "ask", f"not an ask{diag}"


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf .venv-backup",
        "rm -rf my_node_modules",
        "rm -rf dist",
        "rm -rf build",
        "rm -rf target",
        "rm -rf node_modules src/generated",
    ],
    ids=["venv-prefix", "name-suffix", "dist", "build", "target", "mixed-operands"],
)
def test_lookalike_and_ambiguous_dirs_still_ask(
    command: str,
    run_pretooluse: Callable[[dict[str, Any]], subprocess.CompletedProcess[str]],
) -> None:
    """Verify the exemption needs a whole-segment match and covers every operand."""
    # Given a delete whose target only resembles a regenerable artifact dir
    payload = _bash(command)

    # When the PreToolUse dispatcher evaluates it
    proc = run_pretooluse(payload)

    # Then the hook asks
    diag = f"\n  stderr={proc.stderr!r}\n  stdout={proc.stdout!r}"
    assert proc.returncode == 0, f"exit={proc.returncode}{diag}"
    assert proc.stdout, f"expected an ask decision on stdout{diag}"
    decision = json.loads(proc.stdout)["hookSpecificOutput"]
    assert decision["permissionDecision"] == "ask", f"not an ask{diag}"


@pytest.mark.parametrize(
    "command",
    ["/bin/rm -rf src/generated", "sudo rm -rf src/generated", "command rm -rf src/generated"],
    ids=["absolute-path", "sudo", "command-builtin"],
)
def test_rm_reached_by_another_spelling_asks(
    command: str,
    run_pretooluse: Callable[[dict[str, Any]], subprocess.CompletedProcess[str]],
) -> None:
    """Verify invoking rm by path or through a wrapper still reaches the prompt."""
    # Given a recursive project delete that does not spell rm as a bare word
    payload = _bash(command)

    # When the PreToolUse dispatcher evaluates it
    proc = run_pretooluse(payload)

    # Then the hook asks
    diag = f"\n  stderr={proc.stderr!r}\n  stdout={proc.stdout!r}"
    assert proc.returncode == 0, f"exit={proc.returncode}{diag}"
    assert proc.stdout, f"expected an ask decision on stdout{diag}"
    decision = json.loads(proc.stdout)["hookSpecificOutput"]
    assert decision["permissionDecision"] == "ask", f"not an ask{diag}"


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf /tmp",
        "rm -rf $TMPDIR",
        "rm -rf /private/tmp",
        "rm -rf /tmp/",
        "rm -rf /tmp/*",
        "rm -rf '${TMPDIR}/'",
    ],
    ids=[
        "tmp-root",
        "tmpdir-root",
        "private-tmp-root",
        "trailing-slash",
        "glob-of-root",
        "braced-trailing-slash",
    ],
)
def test_deleting_the_temp_root_itself_asks(
    command: str,
    run_pretooluse: Callable[[dict[str, Any]], subprocess.CompletedProcess[str]],
) -> None:
    """Verify wiping a whole shared temp directory still needs confirmation."""
    # Given a recursive delete of the temp root rather than a path inside it
    payload = _bash(command)

    # When the PreToolUse dispatcher evaluates it
    proc = run_pretooluse(payload)

    # Then the hook asks
    diag = f"\n  stderr={proc.stderr!r}\n  stdout={proc.stdout!r}"
    assert proc.returncode == 0, f"exit={proc.returncode}{diag}"
    assert proc.stdout, f"expected an ask decision on stdout{diag}"
    decision = json.loads(proc.stdout)["hookSpecificOutput"]
    assert decision["permissionDecision"] == "ask", f"not an ask{diag}"


@pytest.mark.parametrize(
    "command",
    [
        "rm --force notes.txt",
        "rm --interactive report.txt",
        "rm -f --preserve-root notes.txt",
        "rm -f notes.txt",
        "echo hello",
    ],
    ids=["long-force", "long-interactive", "preserve-root", "short-force", "benign"],
)
def test_non_recursive_flags_containing_r_pass_through(
    command: str,
    run_pretooluse: Callable[[dict[str, Any]], subprocess.CompletedProcess[str]],
) -> None:
    """Verify a long flag that merely contains 'r' is not read as recursive."""
    # Given a non-recursive rm whose flag spelling contains the letter r
    payload = _bash(command)

    # When the PreToolUse dispatcher evaluates it
    proc = run_pretooluse(payload)

    # Then nothing asks
    diag = f"\n  stderr={proc.stderr!r}\n  stdout={proc.stdout!r}"
    assert proc.returncode == 0, f"exit={proc.returncode}{diag}"
    assert "permissionDecision" not in proc.stdout, f"unexpected ask{diag}"


@pytest.mark.parametrize(
    ("command", "rule"),
    [("rm -rf ~", "rm-home"), ("rm -rf /etc", "rm-system"), ("rm -rf .", "rm-cwd")],
    ids=["home", "system", "cwd"],
)
def test_catastrophic_target_still_hard_blocks(
    command: str,
    rule: str,
    run_pretooluse: Callable[[dict[str, Any]], subprocess.CompletedProcess[str]],
) -> None:
    """Verify deny beats ask: protect_system fires before this hook prompts.

    Layering guard for the design's safety floor. A catastrophic target must
    never be downgraded from a hard block to a prompt the model could be
    approved through.
    """
    # Given a recursive delete of a catastrophic target
    payload = _bash(command)

    # When the PreToolUse dispatcher evaluates it
    proc = run_pretooluse(payload)

    # Then it is blocked outright, not routed to the prompt
    diag = f"\n  stderr={proc.stderr!r}\n  stdout={proc.stdout!r}"
    assert proc.returncode == 2, f"exit={proc.returncode}{diag}"
    assert rule in proc.stderr, f"wrong rule{diag}"
    assert "permissionDecision" not in proc.stdout, f"downgraded to an ask{diag}"


@pytest.mark.parametrize(
    "command",
    ["rm --rec -f src/generated", "rm --recu src/generated"],
    ids=["abbrev-rec", "abbrev-recu"],
)
def test_abbreviated_long_recursive_flag_asks(
    command: str,
    run_pretooluse: Callable[[dict[str, Any]], subprocess.CompletedProcess[str]],
) -> None:
    """Verify a getopt_long abbreviation of --recursive is read as recursive."""
    # Given a recursive project delete spelled with an abbreviated long flag
    payload = _bash(command)

    # When the PreToolUse dispatcher evaluates it
    proc = run_pretooluse(payload)

    # Then the hook asks
    diag = f"\n  stderr={proc.stderr!r}\n  stdout={proc.stdout!r}"
    assert proc.returncode == 0, f"exit={proc.returncode}{diag}"
    assert proc.stdout, f"expected an ask decision on stdout{diag}"
    decision = json.loads(proc.stdout)["hookSpecificOutput"]
    assert decision["permissionDecision"] == "ask", f"not an ask{diag}"


def test_newline_separated_exempt_deletes_pass_through(
    run_pretooluse: Callable[[dict[str, Any]], subprocess.CompletedProcess[str]],
) -> None:
    """Verify a newline ends a clause, so two exempt deletes stay silent."""
    # Given two exempt deletes on separate lines of one multi-line command
    payload = _bash("rm -rf node_modules\nrm -rf /tmp/build")

    # When the PreToolUse dispatcher evaluates it
    proc = run_pretooluse(payload)

    # Then nothing asks
    diag = f"\n  stderr={proc.stderr!r}\n  stdout={proc.stdout!r}"
    assert proc.returncode == 0, f"exit={proc.returncode}{diag}"
    assert "permissionDecision" not in proc.stdout, f"unexpected ask{diag}"


def test_newline_separated_project_delete_asks(
    run_pretooluse: Callable[[dict[str, Any]], subprocess.CompletedProcess[str]],
) -> None:
    """Verify a later line's project delete is still judged on its own."""
    # Given an exempt delete on the line ahead of a project delete
    payload = _bash("rm -rf /tmp/build\nrm -rf src/generated")

    # When the PreToolUse dispatcher evaluates it
    proc = run_pretooluse(payload)

    # Then the hook asks
    diag = f"\n  stderr={proc.stderr!r}\n  stdout={proc.stdout!r}"
    assert proc.returncode == 0, f"exit={proc.returncode}{diag}"
    assert proc.stdout, f"expected an ask decision on stdout{diag}"
    decision = json.loads(proc.stdout)["hookSpecificOutput"]
    assert decision["permissionDecision"] == "ask", f"not an ask{diag}"


def test_non_bash_tool_ignored(
    run_pretooluse: Callable[[dict[str, Any]], subprocess.CompletedProcess[str]],
) -> None:
    """Verify a non-Bash event carrying rm text in its payload passes through."""
    # Given a Write whose content merely mentions a recursive delete
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Write",
        "tool_input": {"file_path": "/tmp/notes.md", "content": "rm -rf src/generated"},  # noqa: S108
    }

    # When the PreToolUse dispatcher evaluates it
    proc = run_pretooluse(payload)

    # Then nothing asks
    assert proc.returncode == 0
    assert "permissionDecision" not in proc.stdout


@pytest.mark.parametrize(
    "command",
    [
        'S=/private/tmp/scratch; rm -rf "$S/smoke-vault" "$S/proj"',
        "S=/tmp/work; rm -rf $S/out",
        'S=/tmp/work; rm -rf "${S}/out"',
        "export S=/tmp/work; rm -rf $S",
        "S=/tmp/work && rm -rf $S/out",
        "S=/tmp/work\nrm -rf $S/out",
        "R=/repo; rm -rf $R/node_modules",
    ],
    ids=[
        "reported-shape",
        "bare-ref",
        "braced-ref",
        "export-prefix",
        "assign-then-and",
        "newline-separated",
        "artifact-dir-under-var",
    ],
)
def test_temp_path_reached_through_a_variable_passes_through(
    command: str,
    run_pretooluse: Callable[[dict[str, Any]], subprocess.CompletedProcess[str]],
) -> None:
    """Verify binding a temp path to a variable first does not manufacture a prompt.

    The hook runs before the shell expands anything, so without resolution the
    operand reads as an opaque `$S/...` token and every one of these prompts.
    """
    # Given a delete whose exempt target is routed through a shell variable
    payload = _bash(command)

    # When the PreToolUse dispatcher evaluates it
    proc = run_pretooluse(payload)

    # Then nothing asks
    diag = f"\n  stderr={proc.stderr!r}\n  stdout={proc.stdout!r}"
    assert proc.returncode == 0, f"exit={proc.returncode}{diag}"
    assert "permissionDecision" not in proc.stdout, f"unexpected ask{diag}"


@pytest.mark.parametrize(
    "command",
    [
        "S=$(mktemp -d); rm -rf $S/out",
        "S=/tmp/work; S=$(mktemp -d); rm -rf $S/out",
        "test -d /tmp/work && S=/tmp/work; rm -rf $S/out",
        "S=/tmp/work; test -d /x && S=/srv/data; rm -rf $S/out",
        "rm -rf $SCRATCH/out",
        "S=/tmp/work; rm -rf $S/../../etc",
        "S=~/repos/proj; rm -rf $S/build",
        "S=/tmp; rm -rf $S",
        "S=/tmp/work; rm -rf '$S/out'",
        "S=/tmp/work echo hi; rm -rf $S/out",
        "S=/tmp/work; S+=/../../etc; rm -rf $S",
        "S=/tmp/work; local S=/srv/data; rm -rf $S",
        "S=/tmp/work; unset S; rm -rf $S",
        "TMPDIR=$(pwd); rm -rf $TMPDIR/src",
        "S=/tmp/work & rm -rf $S/out",
        "S=/tmp/work | rm -rf $S/out",
    ],
    ids=[
        "command-substitution",
        "reassigned-unresolvable",
        "conditional-assignment",
        "conditional-reassignment",
        "never-assigned",
        "traversal-after-resolution",
        "variable-holds-a-project-path",
        "resolves-to-the-temp-root",
        "single-quoted-reference",
        "environment-prefix",
        "append-rebinding",
        "keyword-rebinding",
        "unset-rebinding",
        "tmpdir-rebound-unresolvably",
        "backgrounded-assignment",
        "piped-assignment",
    ],
)
def test_unresolvable_or_unsafe_variable_target_still_asks(
    command: str,
    run_pretooluse: Callable[[dict[str, Any]], subprocess.CompletedProcess[str]],
) -> None:
    """Verify resolution only ever removes a prompt for a provably exempt path.

    Safety floor for the variable resolution: a value the pass cannot evaluate,
    one an earlier binding must not survive, and one that resolves to a real
    path all keep the confirmation they had before.
    """
    # Given a delete whose variable target is unresolvable or resolves outside a temp root
    payload = _bash(command)

    # When the PreToolUse dispatcher evaluates it
    proc = run_pretooluse(payload)

    # Then the hook asks
    diag = f"\n  stderr={proc.stderr!r}\n  stdout={proc.stdout!r}"
    assert proc.returncode == 0, f"exit={proc.returncode}{diag}"
    assert proc.stdout, f"expected an ask decision on stdout{diag}"
    decision = json.loads(proc.stdout)["hookSpecificOutput"]
    assert decision["permissionDecision"] == "ask", f"not an ask{diag}"
