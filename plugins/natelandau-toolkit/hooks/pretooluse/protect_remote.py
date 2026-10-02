"""PreToolUse hook: put a human in the loop for remote-host commands.

The goal is preventing destructive actions ON remote machines, not remote
access itself. A hook cannot judge whether an arbitrary remote command is
destructive (the payload is a quoted argument buried in ssh flags), so every
command that reaches a remote host routes to the interactive permission
prompt (`permissionDecision: "ask"`) and the user decides per invocation:

- ssh sessions and remote command execution.
- scp / sftp transfers (either direction).
- rsync with a remote endpoint (host:path, rsync://, or -e/--rsh); local
  rsync never prompts.
- ansible remote execution (ansible, ansible-playbook, ansible-console,
  ansible-pull), including `uv run` / `uvx` wrapped forms.

Deliberately not matched: local-only companions (ssh-keygen, ssh-add,
ssh-agent, ansible-vault, ansible-galaxy, ansible-doc, ansible-inventory,
ansible-config, ansible-lint) and ssh-copy-id (requires an interactive
password, so it cannot run unattended).

Under `permission_mode == "bypassPermissions"` a hook ask is not documented
to prompt, so the ask Decision also carries advisory `context` telling the
model destructive operations on remote hosts are forbidden: prompt if asks
are honored, run-with-warning if not. protect_system's exit-2 blocks fire in
every mode and win over an ask, so catastrophic substrings inside a remote
command (`ssh host 'rm -rf ~'`) stay hard-blocked.

Hosts listed in `trusted_remote_hosts` in the GLOBAL config run without a
prompt. Trust applies only when every clause that reaches a host is an ssh,
autossh, sftp, scp, or rsync launch `lib.remote_hosts` can read, every host
it names is trusted, and no ssh command run there reaches another host. It
never waives ansible (its hosts live in an inventory), a project rule, or a
block. The project config cannot set the list; see `lib.config`.

Rule data lives in `protect_remote.rules.toml` next to this file; the
script loads it on every invocation. Edit that file to add, remove, or tune
a rule (per-rule `action` may be "ask" or "block").
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from lib import bash, remote_hosts, rules
from lib.io import Decision

if TYPE_CHECKING:
    from lib.config import Config

ID = "protect-remote"
RULES_FILE = Path(__file__).parent / "protect_remote.rules.toml"
REMOTE_FIELDS = rules.BLOCK_RULE_FIELDS
OPTIONAL_FIELDS = frozenset({"action"})
# Built-in rules whose every match is a launch `lib.remote_hosts` can read the
# host out of, so a trusted host may waive them. ansible-remote is absent: its
# hosts come from an inventory, not the command line.
HOST_RULE_IDS = frozenset({"rsync-remote", "ssh-exec", "scp", "sftp"})

# Advisory fed to the model when bypassPermissions suppresses the prompt.
_BYPASS_CONTEXT = (
    "[protect-remote] This command touches a remote host and permission "
    "bypass is active. If no permission prompt appeared, proceed only if "
    "the command is non-destructive on the remote machine; never run "
    "destructive operations on remote hosts."
)


def evaluate(event: dict[str, Any], cfg: Config) -> Decision | None:
    """Return an ask (or block) Decision for a remote-host command, else None.

    Matches the bash command against the built-in `[[rule]]` list plus any
    additive per-project rules. Block-action rules are matched ahead of
    ask-action rules (two passes over the loaded rules) so a project
    `action = "block"` rule outranks a built-in ask for the same command,
    mirroring the dispatcher's deny-beats-ask precedence; all built-ins are
    asks, so this can only harden, never soften. An `action = "ask"` match
    routes to the permission prompt; under bypassPermissions the ask also
    carries the advisory context fallback. An `action = "block"` match
    (available to per-project rules) hard-blocks.
    """
    if event.get("tool_name") != "Bash":
        return None
    command: str = (event.get("tool_input") or {}).get("command", "")
    if not command:
        return None
    remote_rules = rules.load_all_rules(
        RULES_FILE,
        "rule",
        required=REMOTE_FIELDS,
        optional=OPTIONAL_FIELDS,
        project_dir=cfg.project_dir,
        label="protect_remote",
    )
    fields = {"tool_name": "Bash", "command": command}
    # Deny beats ask: check block-action rules across the whole list before any
    # ask, so a project hard-block is not shadowed by an earlier built-in ask.
    block_rules = tuple(rule for rule in remote_rules if rule.action == "block")
    ask_rules = tuple(rule for rule in remote_rules if rule.action == "ask")
    matched = rules.first_match(block_rules, text=command, fields=fields)
    if matched is not None:
        return Decision.blocked(ID, f"'{matched.id}': {matched.reason}")
    matched = rules.first_match(ask_rules, text=command, fields=fields)
    trusted = remote_hosts.resolve(cfg.trusted_remote_hosts)
    if matched is None or (trusted and _reaches_only_trusted(command, ask_rules, trusted)):
        return None
    decision = Decision.ask_user(ID, f"'{matched.id}': {matched.reason}")
    if event.get("permission_mode") == "bypassPermissions":
        return replace(decision, context=_BYPASS_CONTEXT)
    return decision


def _reaches_only_trusted(
    command: str, ask_rules: tuple[rules.Rule, ...], trusted: remote_hosts.TrustedHosts
) -> bool:
    """Return whether every remote launch in `command` reaches only trusted hosts.

    Judged clause by clause with the command's own literal assignments
    replayed, so `H=nas; ssh $H` reads as ssh to nas. A clause any non-host
    rule matches, or whose launch cannot be read, fails the whole command.
    """
    if remote_hosts.REFUSED_ENV.search(command):
        return False
    # Compared by value against the built-in file, so a project rule that
    # reuses a built-in id is never waivable.
    waivable = tuple(
        rule
        for rule in rules.load_rules(
            RULES_FILE, "rule", required=REMOTE_FIELDS, optional=OPTIONAL_FIELDS
        )
        if rule.id in HOST_RULE_IDS
    )
    seen_remote = False
    for clause in bash.resolve_assignments(command, include_pipes=True):
        fields = {"tool_name": "Bash", "command": clause}
        hits = [r for r in ask_rules if rules.rule_matches(r, text=clause, fields=fields)]
        if not hits:
            continue
        seen_remote = True
        if not all(rule in waivable for rule in hits):
            return False
        call = remote_hosts.parse_clause(clause)
        if call is None or not all(trusted.trusts(host) for host in call.hosts):
            return False
        hop_fields = {"tool_name": "Bash", "command": call.remote_command}
        if call.remote_command and rules.first_match(
            ask_rules, text=call.remote_command, fields=hop_fields
        ):
            return False
    # A rule that matched the whole command but no single clause spans a
    # clause boundary, so no one clause's hosts account for it.
    return seen_remote
