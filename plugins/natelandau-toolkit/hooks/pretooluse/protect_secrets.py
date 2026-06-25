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

Rule data (allowlist, sensitive-file rules, bash-command rules) lives in
`protect_secrets.rules.toml` next to this file; the script loads it on
every invocation. Edit that file to add, remove, or tune a rule.

Ported from karanb192/claude-code-hooks `protect-secrets.js`.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from lib import rules
from lib.io import Decision

if TYPE_CHECKING:
    import re
    from collections.abc import Mapping

    from lib.config import Config

ID = "protect-secrets"
RULES_FILE = Path(__file__).parent / "protect_secrets.rules.toml"
# Required [[rule]] fields shared with protect_system (see rules.BLOCK_RULE_FIELDS).
# Each rule additionally sets `field` to target a named input (file_path or
# command), so one list serves every tool.
SECRET_FIELDS = rules.BLOCK_RULE_FIELDS

# Maps a tool name to the verb used in the user-facing block message.
ACTION_VERBS: dict[str, str] = {
    "Read": "read",
    "Edit": "modify",
    "Write": "write to",
    "Bash": "execute",
}


def _is_allowlisted(text: str, allowlist: tuple[re.Pattern[str], ...]) -> bool:
    """Return whether the input matches any safe-template pattern."""
    return any(p.search(text) for p in allowlist)


def _scrub_allowlisted(command: str, allowlist: tuple[re.Pattern[str], ...]) -> str:
    """Drop allowlisted template tokens from a Bash command before rule matching.

    The allowlist exempts safe templates (`.env.example`, ...), but a template
    reference must not suppress a *separate* secret access in the same compound
    command. Matching the allowlist against the whole command let a trailing
    `&& cat .env.example` mask an earlier `cat ~/.ssh/id_rsa`. Removing only the
    allowlisted tokens lets the template pass while any real secret access in
    the rest of the command is still seen. A template name is never a real
    secret file, so dropping it can never hide one.
    """
    return " ".join(tok for tok in command.split() if not _is_allowlisted(tok, allowlist))


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


def evaluate(event: dict[str, Any], cfg: Config) -> Decision | None:
    """Return a block Decision for a sensitive-file access, else None.

    Builds the tool input into named fields, short-circuits on an
    allowlisted template, then matches one `[[rule]]` list (each rule
    targeting a named field). Returns a blocking Decision with the BLOCKED
    reason string, or None when allowed.
    """
    tool_name = event.get("tool_name", "")
    tool_input = event.get("tool_input") or {}
    if tool_name not in ("Read", "Edit", "Write", "Bash"):
        return None
    # Read once; may raise on malformed TOML (caught by caller / main).
    data = rules.read_toml(RULES_FILE)
    allowlist = rules.parse_pattern_list(data, "allowlist")
    # Built-in rules plus any additive per-project rules. Project rules are
    # blocking-only (the allowlist is never extended) and fail open.
    project_rules = rules.load_project_rules(
        RULES_FILE.name, "rule", required=SECRET_FIELDS, project_dir=cfg.project_dir
    )
    # This hook matches named fields and passes no primary `text` to the
    # matcher, so a project rule that sets neither `field` nor `conditions`
    # can never fire. Surface that misconfiguration instead of silently
    # accepting an inert rule (built-in rules all target a field).
    for rule in project_rules:
        if rule.match_field is None and not rule.conditions:
            print(  # noqa: T201
                f"protect_secrets: project rule {rule.id!r} sets no 'field' or "
                f"'conditions' and cannot match; set field = \"file_path\" "
                f"(or command/content) or use conditions.",
                file=sys.stderr,
            )
    secret_rules = (*rules.parse_rules(data, "rule", required=SECRET_FIELDS), *project_rules)
    fields = _match_fields(tool_name, tool_input)

    # A safe template as the whole file_path (Read/Edit/Write of a single
    # path) short-circuits before any rule.
    if _is_allowlisted(fields["file_path"], allowlist):
        return None
    # For Bash, scrub only the allowlisted template tokens from the command so
    # a `.env.example` reference cannot suppress a separate secret access in
    # the same compound command. Whole-command detection is otherwise intact.
    fields["command"] = _scrub_allowlisted(fields["command"], allowlist)

    # One rule list serves every tool because each rule targets a named
    # field: a file_path rule can't match a Bash call (empty file_path),
    # and a command rule can't match a file edit.
    matched = rules.first_match(secret_rules, fields=fields)
    if matched:
        return Decision.blocked(matched.id, f"Cannot {ACTION_VERBS[tool_name]}: {matched.reason}")
    return None
