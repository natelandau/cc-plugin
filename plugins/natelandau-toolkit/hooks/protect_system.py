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

Override the level with `CLAUDE_PROTECT_SYSTEM_LEVEL`.

Secret reads and git destructive ops are intentionally not duplicated
here; see `protect_secrets.py` and `enforce_branch_protection.py`.

Rule data lives in `protect_system.rules.toml` next to this file; the
script loads it on every invocation. Edit that file to add, remove, or
tune a rule.

Adapted from karanb192/claude-code-hooks `block-dangerous-commands.js`.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Mapping

LEVELS: dict[str, int] = {"critical": 1, "high": 2, "strict": 3}
DEFAULT_LEVEL = "high"
LEVEL_ENV_VAR = "CLAUDE_PROTECT_SYSTEM_LEVEL"
RULES_FILE = Path(__file__).parent / "protect_system.rules.toml"
RULE_FIELDS = frozenset({"level", "id", "pattern", "reason"})


@dataclass(frozen=True, slots=True)
class Rule:
    """Pattern-matched system-destruction rule.

    `level` gates whether the rule fires at the active threshold.
    `pattern` is a regex tested via `re.search` with `re.IGNORECASE`.
    `id` is a stable slug shown in the block message; users can grep
    it out of CI logs or paste it back as feedback when refining rules.
    `reason` is the human-facing explanation appended to the block.
    """

    level: str
    id: str
    pattern: str
    reason: str


def _require_str(entry: Mapping[str, object], key: str, idx: int) -> str:
    """Return entry[key] as a str or raise TypeError naming the offender.

    The TOML loader yields `object`-typed values, so every required field
    is unwrapped through this helper before reaching the Rule constructor.
    Keeps the type narrowing in one place and gives a uniform error shape.
    """
    value = entry[key]
    if not isinstance(value, str):
        msg = f"rule[{idx}].{key} must be a string, got {type(value).__name__}"
        raise TypeError(msg)
    return value


def _load_rules(path: Path) -> tuple[Rule, ...]:
    """Parse the rules TOML file into an ordered tuple of Rule entries.

    Validate that every entry carries exactly the required string fields
    and that `level` is a known threshold, so a typo in TOML surfaces as
    a clear error instead of a Rule built with non-string fields.

    Args:
        path: Location of the rules TOML file.

    Returns:
        Rules in declaration order, ready for first-match-wins iteration.
    """
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    entries = data.get("rule")
    if not isinstance(entries, list):
        msg = "missing top-level 'rule' array"
        raise TypeError(msg)
    rules: list[Rule] = []
    for idx, raw_entry in enumerate(entries):
        if not isinstance(raw_entry, dict):
            msg = f"rule[{idx}] is not a table"
            raise TypeError(msg)
        # tomllib types entries as dict[str, Any]; cast to a covariant
        # Mapping so _require_str can read fields without ty rejecting the
        # invariant dict generic.
        entry = cast("Mapping[str, object]", raw_entry)
        keys = entry.keys()
        missing = RULE_FIELDS - keys
        if missing:
            msg = f"rule[{idx}] missing fields: {sorted(missing)}"
            raise ValueError(msg)
        extra = keys - RULE_FIELDS
        if extra:
            msg = f"rule[{idx}] has unexpected fields: {sorted(extra)}"
            raise ValueError(msg)
        level = _require_str(entry, "level", idx)
        if level not in LEVELS:
            msg = f"rule[{idx}] has unknown level {level!r}"
            raise ValueError(msg)
        rules.append(
            Rule(
                level=level,
                id=_require_str(entry, "id", idx),
                pattern=_require_str(entry, "pattern", idx),
                reason=_require_str(entry, "reason", idx),
            )
        )
    return tuple(rules)


def _active_threshold() -> int:
    """Return the numeric threshold from the env var, falling back to default."""
    raw = os.environ.get(LEVEL_ENV_VAR, DEFAULT_LEVEL).lower()
    return LEVELS.get(raw, LEVELS[DEFAULT_LEVEL])


def _first_match(text: str, rules: tuple[Rule, ...], threshold: int) -> Rule | None:
    """Return the first rule firing at or below the active threshold."""
    for rule in rules:
        if LEVELS[rule.level] > threshold:
            continue
        if re.search(rule.pattern, text, re.IGNORECASE):
            return rule
    return None


def _block(rule: Rule) -> None:
    """Print BLOCKED message to stderr and exit 2."""
    print(  # noqa: T201
        f"BLOCKED [{rule.id}]: Cannot execute: {rule.reason}",
        file=sys.stderr,
    )
    sys.exit(2)


def main() -> None:
    """Entry point for the PreToolUse hook."""
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    if data.get("tool_name") != "Bash":
        sys.exit(0)

    command: str = (data.get("tool_input") or {}).get("command", "")
    if not command:
        sys.exit(0)

    # Load rules at invocation, not import, so a malformed TOML surfaces a
    # focused error message rather than a confusing import-time traceback.
    try:
        rules = _load_rules(RULES_FILE)
    except (OSError, tomllib.TOMLDecodeError, TypeError, ValueError) as exc:
        print(  # noqa: T201
            f"protect_system: failed to load {RULES_FILE.name}: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)

    rule = _first_match(command, rules, _active_threshold())
    if rule:
        _block(rule)
    sys.exit(0)


if __name__ == "__main__":
    main()
