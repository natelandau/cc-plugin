#!/usr/bin/env -S uv run --script

# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///

"""PreToolUse hook: blocks reads, edits, and exfiltration of sensitive files.

For Read/Edit/Write the file_path is matched against a list of sensitive
file regexes (`.env`, SSH keys, AWS credentials, PEM/key files, etc.).
For Bash the command is matched against a list of risky patterns
(`cat .env`, env dumps, `scp` of secrets, deletion of credentials, etc.).
Allowlisted templates like `.env.example` always pass through.

Three escalating thresholds gate which rules apply:

- `critical` -- only the highest-impact rules (private keys, .env, AWS).
- `high` (default) -- adds secrets files, env dumps, exfiltration patterns.
- `strict` -- adds dotfiles that may contain credentials (`.gitconfig`,
  `database.yaml`, `known_hosts`).

Set the level via the `[hooks.protect-secrets]` `level` key in
`natelandau-toolkit.toml`.

Rule data (allowlist, sensitive-file rules, bash-command rules) lives in
`protect_secrets.rules.toml` next to this file; the script loads it on
every invocation. Edit that file to add, remove, or tune a rule.

Ported from karanb192/claude-code-hooks `protect-secrets.js`.
"""

from __future__ import annotations

import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

from lib.config import Config, load_config
from lib.io import Decision, emit_block, emit_pre_advisory, read_payload

LEVELS: dict[str, int] = {"critical": 1, "high": 2, "strict": 3}
DEFAULT_LEVEL = "high"
RULES_FILE = Path(__file__).parent / "protect_secrets.rules.toml"
RULE_FIELDS = frozenset({"level", "id", "pattern", "reason"})

# Maps a tool name to the verb used in the user-facing block message.
ACTION_VERBS: dict[str, str] = {
    "Read": "read",
    "Edit": "modify",
    "Write": "write to",
    "Bash": "execute",
}


@dataclass(frozen=True, slots=True)
class Rule:
    """Pattern-matched secrets rule.

    `level` gates whether the rule fires at the active threshold.
    `pattern` is a regex tested via `re.search` with `re.IGNORECASE`.
    `id` is a stable slug shown in the block message; users can grep it
    out of CI logs or paste it back as feedback when refining rules.
    `reason` is the human-facing explanation appended to the block.
    """

    level: str
    id: str
    pattern: str
    reason: str


@dataclass(frozen=True, slots=True)
class RuleSet:
    """Bundle of rule data loaded from the sibling TOML.

    Groups the three pieces of rule data so a single `_load_rules()` call
    parses the file once and the caller threads one value through main()
    instead of three. All regexes are pre-compiled with `re.IGNORECASE`
    at load time so malformed patterns surface as load errors and the
    hot path avoids re-compilation on every invocation.
    """

    allowlist: tuple[re.Pattern[str], ...]
    sensitive_files: tuple[tuple[re.Pattern[str], Rule], ...]
    bash_patterns: tuple[tuple[re.Pattern[str], Rule], ...]


def _require_str(entry: Mapping[str, object], key: str, idx: int, section: str) -> str:
    """Return entry[key] as a str or raise TypeError naming the offender.

    The TOML loader yields `object`-typed values, so every required field
    is unwrapped through this helper before reaching the Rule constructor.
    Keeps the type narrowing in one place and gives a uniform error shape.
    """
    value = entry[key]
    if not isinstance(value, str):
        msg = f"{section}[{idx}].{key} must be a string, got {type(value).__name__}"
        raise TypeError(msg)
    return value


def _parse_rule_list(raw: object, section: str) -> tuple[tuple[re.Pattern[str], Rule], ...]:
    """Validate a TOML array-of-tables into compiled-pattern + Rule pairs.

    Reused for both `[[sensitive_file]]` and `[[bash_pattern]]` because they
    share the same field schema. Patterns are compiled with `re.IGNORECASE`
    during load so a bad regex raises here, not in the matching hot path.
    """
    if not isinstance(raw, list):
        msg = f"missing or non-array '{section}' section"
        raise TypeError(msg)
    compiled: list[tuple[re.Pattern[str], Rule]] = []
    for idx, raw_entry in enumerate(raw):
        if not isinstance(raw_entry, dict):
            msg = f"{section}[{idx}] is not a table"
            raise TypeError(msg)
        # tomllib types entries as dict[str, Any]; cast to a covariant
        # Mapping so _require_str can read fields without ty rejecting the
        # invariant dict generic.
        from typing import cast

        entry = cast("Mapping[str, object]", raw_entry)
        keys = entry.keys()
        missing = RULE_FIELDS - keys
        if missing:
            msg = f"{section}[{idx}] missing fields: {sorted(missing)}"
            raise ValueError(msg)
        extra = keys - RULE_FIELDS
        if extra:
            msg = f"{section}[{idx}] has unexpected fields: {sorted(extra)}"
            raise ValueError(msg)
        level = _require_str(entry, "level", idx, section)
        if level not in LEVELS:
            msg = f"{section}[{idx}] has unknown level {level!r}"
            raise ValueError(msg)
        rule = Rule(
            level=level,
            id=_require_str(entry, "id", idx, section),
            pattern=_require_str(entry, "pattern", idx, section),
            reason=_require_str(entry, "reason", idx, section),
        )
        compiled.append((re.compile(rule.pattern, re.IGNORECASE), rule))
    return tuple(compiled)


def _load_rules(path: Path) -> RuleSet:
    """Parse the rules TOML file into an immutable RuleSet.

    Validate that the allowlist is a list of strings and that each rule
    section carries the required string fields with a known `level`, so
    a typo in TOML surfaces as a clear error instead of a Rule built
    from non-string fields.

    Args:
        path: Location of the rules TOML file.

    Returns:
        Allowlist plus sensitive-file and bash-command rules, each in
        declaration order for first-match-wins iteration.
    """
    with path.open("rb") as fh:
        data = tomllib.load(fh)

    raw_allowlist = data.get("allowlist")
    if not isinstance(raw_allowlist, list):
        msg = "missing or non-array 'allowlist' section"
        raise TypeError(msg)
    allowlist: list[re.Pattern[str]] = []
    for idx, entry in enumerate(raw_allowlist):
        if not isinstance(entry, str):
            msg = f"allowlist[{idx}] must be a string, got {type(entry).__name__}"
            raise TypeError(msg)
        allowlist.append(re.compile(entry, re.IGNORECASE))

    return RuleSet(
        allowlist=tuple(allowlist),
        sensitive_files=_parse_rule_list(data.get("sensitive_file"), "sensitive_file"),
        bash_patterns=_parse_rule_list(data.get("bash_pattern"), "bash_pattern"),
    )


def _threshold(cfg: Config) -> int:
    """Return the numeric threshold from config, defaulting to 'high'."""
    raw = cfg.option("protect-secrets", "level", DEFAULT_LEVEL).lower()
    return LEVELS.get(raw, LEVELS[DEFAULT_LEVEL])


def _is_allowlisted(text: str, allowlist: tuple[re.Pattern[str], ...]) -> bool:
    """Check if the input matches any safe-template pattern."""
    return any(p.search(text) for p in allowlist)


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
    """Return a block Decision for a sensitive-file access, else None.

    Checks the tool name and input against sensitive-file and bash-command
    rules filtered by the configured threshold level. Returns a blocking
    Decision with the BLOCKED reason string, or None when the tool call
    is allowed.
    """
    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input") or {}
    if tool_name not in ("Read", "Edit", "Write", "Bash"):
        return None
    rules = _load_rules(RULES_FILE)  # may raise; caught by caller / main
    threshold = _threshold(cfg)
    matched_rule: Rule | None = None

    if tool_name in ("Read", "Edit", "Write"):
        file_path = tool_input.get("file_path", "")
        if file_path and not _is_allowlisted(file_path, rules.allowlist):
            matched_rule = _first_match(file_path, rules.sensitive_files, threshold)
    else:
        command = tool_input.get("command", "")
        if command and not _is_allowlisted(command, rules.allowlist):
            matched_rule = _first_match(command, rules.bash_patterns, threshold)

    if matched_rule:
        return Decision(
            block=True,
            reason=f"BLOCKED [{matched_rule.id}]: Cannot {ACTION_VERBS[tool_name]}: {matched_rule.reason}",
        )
    return None


def main() -> None:
    """Entry point for standalone PreToolUse invocation."""
    payload = read_payload()
    cfg = load_config()
    try:
        decision = evaluate(payload, cfg)
    except (OSError, tomllib.TOMLDecodeError, TypeError, ValueError, re.error) as exc:
        print(f"protect_secrets: failed to load {RULES_FILE.name}: {exc}", file=sys.stderr)  # noqa: T201
        sys.exit(1)
    if decision and decision.block:
        emit_block(decision.reason)
    emit_pre_advisory([])


if __name__ == "__main__":
    main()
