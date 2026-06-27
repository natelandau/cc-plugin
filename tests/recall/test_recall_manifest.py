"""Manifest/wiring validation for the natelandau-recall plugin."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent / "plugins" / "natelandau-recall"
PREFIX = "${CLAUDE_PLUGIN_ROOT}/"

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _parse_frontmatter(text: str) -> dict[str, str] | None:
    """Extract top-level key/value pairs from a YAML frontmatter block.

    Intentionally minimal: handles the flat `key: value` shape used by commands
    in this plugin, plus indented continuation lines. Avoids a PyYAML dep so the
    test suite stays light.
    """
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return None
    fields: dict[str, str] = {}
    current_key: str | None = None
    for line in match.group(1).splitlines():
        if not line.strip():
            continue
        # Indented continuation appends to the previous key's value.
        if line[:1].isspace() and current_key is not None:
            fields[current_key] = f"{fields[current_key]} {line.strip()}"
            continue
        if ":" in line:
            key, _, value = line.partition(":")
            current_key = key.strip()
            fields[current_key] = value.strip()
    return fields


def _command_files() -> list[Path]:
    commands_dir = ROOT / "commands"
    if not commands_dir.is_dir():
        return []
    return sorted(commands_dir.glob("*.md"))


def _hooks_commands() -> list[tuple[str, str]]:
    data = json.loads((ROOT / "hooks" / "hooks.json").read_text())
    return [
        (event, h["command"])
        for event, entries in data.get("hooks", {}).items()
        for entry in entries
        for h in entry.get("hooks", [])
        if h.get("type") == "command"
    ]


def test_plugin_manifest_fields() -> None:
    """Verify plugin.json declares name and description."""
    # Given the manifest
    data = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
    # Then required fields exist
    assert data.get("name") == "natelandau-recall"
    assert "description" in data


@pytest.mark.parametrize(
    ("event", "command"), _hooks_commands(), ids=lambda v: v if isinstance(v, str) else ""
)
def test_command_resolves_and_is_executable(event: str, command: str) -> None:
    """Verify every hooks.json command points at an executable script."""
    # Given a registered command
    assert command.startswith(PREFIX), command
    # When resolved
    resolved = ROOT / command[len(PREFIX) :]
    # Then it exists and is executable
    assert resolved.is_file(), resolved
    assert os.access(resolved, os.X_OK), resolved


@pytest.mark.parametrize("command_path", _command_files(), ids=lambda p: p.name)
def test_command_has_frontmatter(command_path: Path) -> None:
    """Verify every commands/*.md declares description frontmatter."""
    # Given a command file
    # When the frontmatter is parsed
    fields = _parse_frontmatter(command_path.read_text())

    # Then frontmatter is present with a description field
    assert fields is not None, f"{command_path}: missing YAML frontmatter"
    assert "description" in fields, f"{command_path}: frontmatter missing 'description'"
