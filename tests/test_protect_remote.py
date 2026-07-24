"""Characterization tests for protect_remote.py.

Pipes representative bash payloads through the full PreToolUse dispatcher
(as a subprocess) and asserts on the outcome channel: exit 0 with a
permissionDecision "ask" JSON for remote commands, plain exit 0 for
allowed ones. Payloads are stdin data only; nothing is ever executed.
"""

from __future__ import annotations

import importlib
import json
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pytest

from tests._helpers import bash_payload as _bash

if TYPE_CHECKING:
    import subprocess
    from collections.abc import Callable
    from pathlib import Path


@dataclass(frozen=True)
class Case:
    """One protect_remote test case."""

    id: str
    payload: dict[str, Any]
    asks: str | None = None  # rule id expected in the ask reason; None = allowed


ASK_CASES: tuple[Case, ...] = (
    # ssh sessions and remote commands
    Case(id="ssh host asks", payload=_bash("ssh host"), asks="ssh-exec"),
    Case(id="ssh remote cmd asks", payload=_bash("ssh host 'uname -a'"), asks="ssh-exec"),
    Case(id="ssh with port asks", payload=_bash("ssh -p 2222 user@host"), asks="ssh-exec"),
    Case(id="ssh -T git test asks", payload=_bash("ssh -T git@github.com"), asks="ssh-exec"),
    # transfers over ssh
    Case(id="scp push asks", payload=_bash("scp file.txt host:/tmp/"), asks="scp"),
    Case(id="scp pull asks", payload=_bash("scp -r host:src ./dst"), asks="scp"),
    Case(id="sftp asks", payload=_bash("sftp user@host"), asks="sftp"),
    # rsync only with a remote endpoint
    Case(id="rsync push asks", payload=_bash("rsync -av src/ host:/dst/"), asks="rsync-remote"),
    Case(
        id="rsync pull asks",
        payload=_bash("rsync -av user@host:src ./dst"),
        asks="rsync-remote",
    ),
    Case(
        id="rsync daemon uri asks",
        payload=_bash("rsync rsync://host/mod ./dst"),
        asks="rsync-remote",
    ),
    Case(id="rsync -e ssh asks", payload=_bash("rsync -e ssh src/ dst/"), asks="rsync-remote"),
    Case(
        id="rsync bundled -e asks",
        payload=_bash("rsync -avze ssh src/ host:/dst/"),
        asks="rsync-remote",
    ),
    Case(
        id="rsync ipv6 endpoint asks",
        payload=_bash("rsync -av src/ [::1]:/dst/"),
        asks="rsync-remote",
    ),
    # A genuine remote target in a multiline command still fires: the tightened
    # negated class stops at the newline but the endpoint is on the rsync line.
    Case(
        id="rsync remote then newline asks",
        payload=_bash("rsync -av src/ host:/dst/\necho done"),
        asks="rsync-remote",
    ),
    # autossh reconnects an ssh session, so it routes to the prompt too.
    Case(id="autossh asks", payload=_bash("autossh -M 0 host"), asks="ssh-exec"),
    # ansible remote execution (wrappers ride the same substring match)
    Case(
        id="ansible ad-hoc asks",
        payload=_bash("ansible all -m shell -a 'uptime'"),
        asks="ansible-remote",
    ),
    Case(
        id="ansible-playbook asks",
        payload=_bash("ansible-playbook site.yml"),
        asks="ansible-remote",
    ),
    Case(
        id="uv run ansible-playbook asks",
        payload=_bash("uv run ansible-playbook site.yml"),
        asks="ansible-remote",
    ),
    Case(id="uvx ansible asks", payload=_bash("uvx ansible all -m ping"), asks="ansible-remote"),
    Case(id="ansible-pull asks", payload=_bash("ansible-pull -U repo"), asks="ansible-remote"),
    Case(id="ansible-console asks", payload=_bash("ansible-console web"), asks="ansible-remote"),
)

ALLOW_CASES: tuple[Case, ...] = (
    Case(id="ssh-keygen allowed", payload=_bash("ssh-keygen -t ed25519")),
    Case(id="ssh-add allowed", payload=_bash("ssh-add -l")),
    Case(id="ssh-agent allowed", payload=_bash("ssh-agent -s")),
    # Deliberate exemption (interactive password required) and regression
    # guard that the \bssh\s pattern skips ssh- prefixed tools.
    Case(id="ssh-copy-id allowed", payload=_bash("ssh-copy-id user@host")),
    Case(id="local rsync allowed", payload=_bash("rsync -av src/ dst/")),
    # A newline is a command separator: a colon or `-e` flag in a later command
    # must not make an earlier local rsync look remote.
    Case(
        id="local rsync then colon command allowed",
        payload=_bash("rsync -av src/ dst/\nmake build:prod"),
    ),
    Case(
        id="local rsync then grep -e allowed",
        payload=_bash("rsync -av src/ dst/\ngrep -e foo bar.txt"),
    ),
    Case(id="ansible-vault allowed", payload=_bash("ansible-vault encrypt file.yml")),
    Case(id="ansible-galaxy allowed", payload=_bash("ansible-galaxy install role")),
    Case(id="ansible-doc allowed", payload=_bash("ansible-doc -l")),
    Case(id="ansible-inventory allowed", payload=_bash("ansible-inventory --list")),
    Case(id="ansible-lint allowed", payload=_bash("ansible-lint site.yml")),
    Case(id="uv run ansible-lint allowed", payload=_bash("uv run ansible-lint")),
    Case(id="benign command allowed", payload=_bash("echo hello")),
)


@pytest.mark.parametrize("case", ASK_CASES + ALLOW_CASES, ids=lambda c: c.id)
def test_protect_remote(
    case: Case,
    run_pretooluse: Callable[[dict[str, Any]], subprocess.CompletedProcess[str]],
) -> None:
    """Verify remote commands ask and local companions pass through."""
    proc = run_pretooluse(case.payload)

    diag = f"\n  stderr={proc.stderr!r}\n  stdout={proc.stdout!r}"
    assert proc.returncode == 0, f"exit={proc.returncode}{diag}"
    if case.asks is None:
        # Allowed: no permissionDecision on stdout (empty or advisory-only).
        assert "permissionDecision" not in proc.stdout, f"unexpected ask{diag}"
        return
    assert proc.stdout, f"expected an ask decision on stdout{diag}"
    decision = json.loads(proc.stdout)["hookSpecificOutput"]
    assert decision["permissionDecision"] == "ask", f"not an ask{diag}"
    assert "[protect-remote]" in decision["permissionDecisionReason"], f"wrong hook{diag}"
    assert case.asks in decision["permissionDecisionReason"], f"wrong rule{diag}"


def test_non_bash_tool_ignored(
    run_pretooluse: Callable[[dict[str, Any]], subprocess.CompletedProcess[str]],
) -> None:
    """A non-Bash tool event passes through untouched."""
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Write",
        "tool_input": {"file_path": "/tmp/x", "content": "ssh host"},  # noqa: S108
    }
    proc = run_pretooluse(payload)
    assert proc.returncode == 0
    assert "permissionDecision" not in proc.stdout


def test_bypass_mode_ask_carries_advisory_context(
    run_pretooluse: Callable[[dict[str, Any]], subprocess.CompletedProcess[str]],
) -> None:
    """Under bypassPermissions the ask also ships the advisory fallback.

    A hook ask is not documented to prompt in bypass mode, so the same JSON
    carries additionalContext: prompt if asks are honored, run-with-warning
    if not.
    """
    payload = _bash("ssh host 'systemctl restart nginx'")
    payload["permission_mode"] = "bypassPermissions"
    proc = run_pretooluse(payload)

    diag = f"\n  stderr={proc.stderr!r}\n  stdout={proc.stdout!r}"
    assert proc.returncode == 0, f"exit={proc.returncode}{diag}"
    decision = json.loads(proc.stdout)["hookSpecificOutput"]
    assert decision["permissionDecision"] == "ask", f"not an ask{diag}"
    assert "remote" in decision["additionalContext"], f"missing advisory{diag}"


def test_interactive_ask_has_no_advisory_context(
    run_pretooluse: Callable[[dict[str, Any]], subprocess.CompletedProcess[str]],
) -> None:
    """A normal interactive ask needs no fallback text."""
    proc = run_pretooluse(_bash("ssh host"))
    decision = json.loads(proc.stdout)["hookSpecificOutput"]
    assert decision["permissionDecision"] == "ask"
    assert "additionalContext" not in decision


def test_destructive_remote_command_still_hard_blocks(
    run_pretooluse: Callable[[dict[str, Any]], subprocess.CompletedProcess[str]],
) -> None:
    """Deny beats ask: protect_system fires on the quoted remote command.

    Layering guard for the design's safety floor. Catastrophic substrings
    hard-block in every permission mode, before this hook's ask is emitted.
    """
    proc = run_pretooluse(_bash("ssh host 'rm -rf ~'"))
    assert proc.returncode == 2, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert "rm-home" in proc.stderr


@pytest.fixture
def remote_module(hooks_dir: Path) -> Any:
    """Import protect_remote with the hooks dir importable."""
    sys.path.insert(0, str(hooks_dir))
    sys.path.insert(0, str(hooks_dir / "pretooluse"))
    try:
        yield importlib.import_module("protect_remote")
    finally:
        sys.path.pop(0)
        sys.path.pop(0)


def _cfg(project_dir: str | None = None) -> Any:
    from lib.config import Config  # ty: ignore[unresolved-import]

    return Config(
        profile="standard", disabled_hooks=frozenset(), hook_options={}, project_dir=project_dir
    )


def _project_rules(tmp_path: Path, content: str) -> str:
    """Write a protect_remote project rules file; return the project dir."""
    d = tmp_path / ".claude" / "natelandau-toolkit"
    d.mkdir(parents=True, exist_ok=True)
    (d / "protect_remote.rules.toml").write_text(content, encoding="utf-8")
    return str(tmp_path)


# A project overlay adding one block rule and one ask rule. The block rule
# targets an ssh command the built-in ssh-exec rule would otherwise ask on, so
# a block outcome proves block-action rules outrank the built-in asks.
_PROJECT_REMOTE = """\
[[rule]]
id = "proj-block-prod"
action = "block"
reason = "production hosts are off-limits from a local shell"
pattern = '\\bssh\\s+prod\\b'

[[rule]]
id = "proj-ask-staging"
action = "ask"
reason = "double-check staging access"
pattern = '\\bstagectl\\b'
"""


def test_project_block_rule_outranks_builtin_ask(remote_module: Any, tmp_path: Path) -> None:
    """Verify a project block rule beats the built-in ssh-exec ask for one command."""
    # Given a project overlay whose block rule targets `ssh prod`
    proj = _project_rules(tmp_path, _PROJECT_REMOTE)
    # When running a command both the block rule and the built-in ssh ask match
    decision = remote_module.evaluate(_bash("ssh prod 'deploy'"), _cfg(project_dir=proj))
    # Then the project block wins over the built-in ask
    assert decision is not None
    assert decision.block
    assert not decision.ask
    assert "[protect-remote]" in decision.reason
    assert "proj-block-prod" in decision.reason


def test_project_ask_rule_still_asks(remote_module: Any, tmp_path: Path) -> None:
    """Verify a project ask rule routes to the prompt, not a hard block."""
    # Given the same overlay with an ask rule for `stagectl`
    proj = _project_rules(tmp_path, _PROJECT_REMOTE)
    # When running a command only the project ask rule matches
    decision = remote_module.evaluate(_bash("stagectl restart"), _cfg(project_dir=proj))
    # Then it asks rather than blocks
    assert decision is not None
    assert decision.ask
    assert not decision.block
    assert "proj-ask-staging" in decision.reason


def test_builtin_ask_unaffected_without_project_block(remote_module: Any, tmp_path: Path) -> None:
    """Verify an ordinary ssh command still asks when no block rule matches."""
    # Given the overlay whose block rule only matches `ssh prod`
    proj = _project_rules(tmp_path, _PROJECT_REMOTE)
    # When running an ssh command the block rule does not target
    decision = remote_module.evaluate(_bash("ssh host"), _cfg(project_dir=proj))
    # Then the built-in ssh-exec ask still fires
    assert decision is not None
    assert decision.ask
    assert not decision.block
    assert "ssh-exec" in decision.reason
