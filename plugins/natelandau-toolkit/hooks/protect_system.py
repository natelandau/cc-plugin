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

import re
import sys
import tomllib
from pathlib import Path
from typing import Any

from lib import rules
from lib.config import Config, load_config
from lib.io import Decision, emit_block, emit_pre_advisory, read_payload

DEFAULT_LEVEL = "high"
RULES_FILE = Path(__file__).parent / "protect_system.rules.toml"
# Fields every [[rule]] entry must carry besides its matcher (pattern or
# conditions). The shared loader validates these and rejects unknown keys.
SYSTEM_FIELDS = frozenset({"id", "level", "reason"})


def _threshold(cfg: Config) -> int:
    """Return the numeric threshold from config, defaulting to 'high'."""
    raw = cfg.option("protect-system", "level", DEFAULT_LEVEL).lower()
    return rules.LEVELS.get(raw, rules.LEVELS[DEFAULT_LEVEL])


def evaluate(payload: dict[str, Any], cfg: Config) -> Decision | None:
    """Return a block Decision for a destructive system command, else None.

    Checks the bash command against system-destruction rules filtered by
    the configured threshold level. Returns a blocking Decision with the
    BLOCKED reason string, or None when the command is allowed.
    """
    if payload.get("tool_name") != "Bash":
        return None
    command: str = (payload.get("tool_input") or {}).get("command", "")
    if not command:
        return None
    # May raise on malformed TOML; caught by caller / main.
    system_rules = rules.load_rules(RULES_FILE, "rule", required=SYSTEM_FIELDS)
    # `command` is the primary match text; also expose named fields so a rule
    # may target one explicitly with `field` (e.g. field = "command").
    fields = {"tool_name": "Bash", "command": command}
    matched = rules.first_match(
        system_rules, text=command, fields=fields, threshold=_threshold(cfg)
    )
    if matched:
        return Decision(
            block=True,
            reason=f"BLOCKED [{matched.id}]: Cannot execute: {matched.reason}",
        )
    return None


def main() -> None:
    """Entry point for the PreToolUse hook."""
    payload = read_payload()
    cfg = load_config()
    try:
        decision = evaluate(payload, cfg)
    except (OSError, tomllib.TOMLDecodeError, TypeError, ValueError, re.error) as exc:
        print(f"protect_system: failed to load {RULES_FILE.name}: {exc}", file=sys.stderr)  # noqa: T201
        sys.exit(1)
    if decision and decision.block:
        emit_block(decision.reason)
    emit_pre_advisory([])


if __name__ == "__main__":
    main()
