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
from pathlib import Path
from typing import TYPE_CHECKING, Any

from lib import rules
from lib.config import Config, load_config
from lib.io import Decision, emit_block, emit_pre_advisory, read_payload

if TYPE_CHECKING:
    from collections.abc import Mapping

DEFAULT_LEVEL = "high"
RULES_FILE = Path(__file__).parent / "protect_secrets.rules.toml"
# Fields every [[rule]] entry must carry besides its matcher (pattern or
# conditions); the shared loader validates these and rejects unknown keys.
# Each rule additionally sets `field` to target a named input (file_path or
# command), so one list serves every tool.
SECRET_FIELDS = frozenset({"id", "level", "reason"})

# Maps a tool name to the verb used in the user-facing block message.
ACTION_VERBS: dict[str, str] = {
    "Read": "read",
    "Edit": "modify",
    "Write": "write to",
    "Bash": "execute",
}


def _threshold(cfg: Config) -> int:
    """Return the numeric threshold from config, defaulting to 'high'."""
    raw = cfg.option("protect-secrets", "level", DEFAULT_LEVEL).lower()
    return rules.LEVELS.get(raw, rules.LEVELS[DEFAULT_LEVEL])


def _is_allowlisted(text: str, allowlist: tuple[re.Pattern[str], ...]) -> bool:
    """Check if the input matches any safe-template pattern."""
    return any(p.search(text) for p in allowlist)


def _match_fields(tool_name: str, tool_input: Mapping[str, object]) -> dict[str, str]:
    """Expose tool input as named fields for rule matching.

    Every rule names the input it targets (via `field`, or a `conditions`
    entry), so one rule list serves all tools: a `file_path` rule simply
    never matches a Bash call, where `file_path` is empty, and a `command`
    rule never matches a file edit. A `conditions` rule can also require
    several of these at once (e.g. a `file_path` plus a `content` substring).
    """
    return {
        "tool_name": tool_name,
        "file_path": str(tool_input.get("file_path", "")),
        "command": str(tool_input.get("command", "")),
        "content": str(tool_input.get("content", "")),
        "old_string": str(tool_input.get("old_string", "")),
        "new_string": str(tool_input.get("new_string", "")),
    }


def evaluate(payload: dict[str, Any], cfg: Config) -> Decision | None:
    """Return a block Decision for a sensitive-file access, else None.

    Builds the tool input into named fields, short-circuits on an
    allowlisted template, then matches one `[[rule]]` list (each rule
    targeting a named field) filtered by the configured threshold. Returns
    a blocking Decision with the BLOCKED reason string, or None when allowed.
    """
    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input") or {}
    if tool_name not in ("Read", "Edit", "Write", "Bash"):
        return None
    # Read once; may raise on malformed TOML (caught by caller / main).
    data = rules.read_toml(RULES_FILE)
    allowlist = rules.parse_pattern_list(data, "allowlist")
    secret_rules = rules.parse_rules(data, "rule", required=SECRET_FIELDS)
    fields = _match_fields(tool_name, tool_input)

    # Safe templates (.env.example) short-circuit before any rule. Both
    # primary inputs are tested; the one irrelevant to this tool is empty.
    if _is_allowlisted(fields["file_path"], allowlist) or _is_allowlisted(
        fields["command"], allowlist
    ):
        return None

    # One rule list serves every tool because each rule targets a named
    # field: a file_path rule can't match a Bash call (empty file_path),
    # and a command rule can't match a file edit.
    matched = rules.first_match(secret_rules, fields=fields, threshold=_threshold(cfg))
    if matched:
        return Decision(
            block=True,
            reason=f"BLOCKED [{matched.id}]: Cannot {ACTION_VERBS[tool_name]}: {matched.reason}",
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
