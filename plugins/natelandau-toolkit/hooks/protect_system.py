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
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from collections.abc import Mapping

from lib.config import Config, load_config
from lib.io import Decision, emit_block, emit_pre_advisory, read_payload

LEVELS: dict[str, int] = {"critical": 1, "high": 2, "strict": 3}
DEFAULT_LEVEL = "high"
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


def _load_rules(path: Path) -> tuple[tuple[re.Pattern[str], Rule], ...]:
    """Parse the rules TOML and pre-compile each pattern.

    Validate that every entry carries exactly the required string fields
    and that `level` is a known threshold, so a typo in TOML surfaces as
    a clear error instead of a Rule built with non-string fields. Patterns
    are compiled with `re.IGNORECASE` during load so a malformed regex
    surfaces here, not in the hot path.

    Args:
        path: Location of the rules TOML file.

    Returns:
        Compiled-pattern + Rule pairs in declaration order, ready for
        first-match-wins iteration.
    """
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    entries = data.get("rule")
    if not isinstance(entries, list):
        msg = "missing top-level 'rule' array"
        raise TypeError(msg)
    compiled: list[tuple[re.Pattern[str], Rule]] = []
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
        rule = Rule(
            level=level,
            id=_require_str(entry, "id", idx),
            pattern=_require_str(entry, "pattern", idx),
            reason=_require_str(entry, "reason", idx),
        )
        compiled.append((re.compile(rule.pattern, re.IGNORECASE), rule))
    return tuple(compiled)


def _threshold(cfg: Config) -> int:
    """Return the numeric threshold from config, defaulting to 'high'."""
    raw = cfg.option("protect-system", "level", DEFAULT_LEVEL).lower()
    return LEVELS.get(raw, LEVELS[DEFAULT_LEVEL])


def _first_match(
    text: str,
    rules: tuple[tuple[re.Pattern[str], Rule], ...],
    threshold: int,
) -> Rule | None:
    """Return the first rule firing at or below the active threshold."""
    for pat, rule in rules:
        if LEVELS[rule.level] > threshold:
            continue
        if pat.search(text):
            return rule
    return None


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
    rules = _load_rules(RULES_FILE)  # may raise; caught by caller / main
    threshold = _threshold(cfg)
    matched_rule = _first_match(command, rules, threshold)
    if matched_rule:
        return Decision(
            block=True,
            reason=f"BLOCKED [{matched_rule.id}]: Cannot execute: {matched_rule.reason}",
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
