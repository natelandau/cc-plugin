"""PreToolUse hook: block system-destructive bash commands.

Block catastrophic and high-risk shell operations that are largely
irreversible:

- Mass deletion of home, root, or system directories
  (`rm -rf ~`, `rm -rf /etc`).
- Removal of a `.git` directory, which discards all history with no
  remote-free way back. Paths inside it stay allowed so unwedging with
  `rm -f .git/index.lock` still works.
- Disk wipes (`dd of=/dev/sda`, `mkfs.ext4 /dev/sda`,
  `diskutil eraseDisk`).
- Fork bombs and init/kernel-panic triggers (`kill -9 1`,
  `pkill -9 init`, `> /proc/sysrq-trigger`).
- Piping remote scripts to a shell (`curl ... | sh`).
- World-writable permissions (`chmod 777`).
- Docker volume deletion and prune ops.
- macOS system-integrity ops (`csrutil disable`, `nvram -c`,
  `tmutil delete`).
- Cloud / IaC catastrophes with explicit auto-confirm flags
  (`terraform destroy --auto-approve`, `aws s3 rb --force`,
  `gcloud ... delete --quiet`, `gh repo delete --yes`).

A command that binds a path to one of its own variables before using it
(`H=$HOME; rm -rf "$H"`) is matched twice: once as written, then once with
those assignments replayed by `bash.resolve_command`. The literal pass runs
first and unchanged, so resolution can only ever add a block, never lose
one. Resolution is narrow by construction (see `resolve_command`), and a
reference it cannot evaluate stays as written and matches nothing, so this
raises the floor for the catastrophic targets rather than guaranteeing one:
a path from a command substitution or the surrounding environment is still
invisible here.

Secret reads and git destructive ops are intentionally not duplicated
here; see `protect_secrets.py` and `enforce_branch_protection.py`.

Rule data lives in `protect_system.rules.toml` next to this file; the
script loads it on every invocation. Edit that file to add, remove, or
tune a rule.

Adapted from karanb192/claude-code-hooks `block-dangerous-commands.js`.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from lib import bash, rules
from lib.io import Decision

if TYPE_CHECKING:
    from lib.config import Config

ID = "protect-system"
RULES_FILE = Path(__file__).parent / "protect_system.rules.toml"
# Required [[rule]] fields shared with protect_secrets (see rules.BLOCK_RULE_FIELDS).
SYSTEM_FIELDS = rules.BLOCK_RULE_FIELDS


def evaluate(event: dict[str, Any], cfg: Config) -> Decision | None:
    """Return a block Decision for a destructive system command, else None.

    Matches the bash command against the built-in `[[rule]]` list plus any
    additive per-project rules. The command is passed both as the primary
    `text` and as a named `command` field so a rule may target it
    explicitly. Returns a blocking Decision with the BLOCKED reason string,
    or None when the command is allowed.
    """
    if event.get("tool_name") != "Bash":
        return None
    command: str = bash.join_continuations((event.get("tool_input") or {}).get("command", ""))
    if not command:
        return None
    # Built-in rules raise on malformed TOML (caught by the driver); project
    # rules are additive and fail open inside load_all_rules.
    system_rules = rules.load_all_rules(
        RULES_FILE,
        "rule",
        required=SYSTEM_FIELDS,
        project_dir=cfg.project_dir,
        label="protect_system",
    )
    # `command` is the primary match text; also expose named fields so a rule
    # may target one explicitly with `field` (e.g. field = "command").
    fields = {"tool_name": "Bash", "command": command}
    matched = rules.first_match(system_rules, text=command, fields=fields)
    if matched:
        # The bracket slug is the hook id a user disables (see Decision.blocked);
        # the rule id rides in the message so the specific rule stays visible.
        return Decision.blocked(ID, f"'{matched.id}': Cannot execute: {matched.reason}")
    # Every rule matches the command as written, so a target the command routes
    # through a variable of its own (`H=$HOME; rm -rf "$H"`) reads as an opaque
    # token and evades the rule that names it. Retry against the resolved text.
    # Second, never first: resolution can only add a block this way, so no rule
    # that fires on the literal command can be lost to a substitution.
    resolved = bash.resolve_command(command)
    if resolved == command:
        return None
    matched = rules.first_match(system_rules, text=resolved, fields={**fields, "command": resolved})
    if matched:
        # Name the resolved form: the operator wrote `$H`, and the rule that
        # fired names a path that appears nowhere in what they typed.
        return Decision.blocked(
            ID,
            f"'{matched.id}': Cannot execute: {matched.reason}"
            f" -- the command's own variables resolve it to: {resolved}",
        )
    return None
