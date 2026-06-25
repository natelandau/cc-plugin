#!/usr/bin/env -S uv run --script

# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///

"""PreToolUse hook: block system-destructive bash commands.

Block catastrophic and high-risk shell operations that are largely
irreversible:

- Mass deletion of home, root, or system directories
  (`rm -rf ~`, `rm -rf /etc`).
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
- `sudo rm`, `crontab -r`.

Three escalating thresholds gate which rules apply:

- `critical` -- only catastrophic, unrecoverable ops.
- `high` (default) -- adds significant-risk ops (`curl|sh`,
  `chmod 777`, docker volume rm).
- `strict` -- adds cautionary ops (`sudo rm`, docker prune,
  `crontab -r`).

Set the level via the `[hooks.protect-system]` `level` key in
`natelandau-toolkit.toml`.

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

from lib import rules
from lib.io import Decision

if TYPE_CHECKING:
    from lib.config import Config

ID = "protect-system"
DEFAULT_LEVEL = "high"
RULES_FILE = Path(__file__).parent / "protect_system.rules.toml"
# Required [[rule]] fields shared with protect_secrets (see rules.THRESHOLD_RULE_FIELDS).
SYSTEM_FIELDS = rules.THRESHOLD_RULE_FIELDS


def evaluate(event: dict[str, Any], cfg: Config) -> Decision | None:
    """Return a block Decision for a destructive system command, else None.

    Matches the bash command against the built-in `[[rule]]` list plus any
    additive per-project rules, filtered by the configured threshold. The
    command is passed both as the primary `text` and as a named `command`
    field so a rule may target it explicitly. Returns a blocking Decision
    with the BLOCKED reason string, or None when the command is allowed.
    """
    if event.get("tool_name") != "Bash":
        return None
    command: str = (event.get("tool_input") or {}).get("command", "")
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
    matched = rules.first_match(
        system_rules,
        text=command,
        fields=fields,
        threshold=rules.threshold(cfg, hook_id=ID, default=DEFAULT_LEVEL),
    )
    if matched:
        return Decision.blocked(matched.id, f"Cannot execute: {matched.reason}")
    return None
