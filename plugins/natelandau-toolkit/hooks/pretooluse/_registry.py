"""Plugins for this stage, in run order. Empty list => the stage is a noop."""

from __future__ import annotations

from lib.profiles import ALL, STANDARD_UP

PLUGINS: list[tuple[str, frozenset[str]]] = [
    ("enforce_branch_protection", ALL),
    ("protect_secrets", ALL),
    ("protect_system", ALL),
    ("enforce_commit_message", STANDARD_UP),
    ("config_protection", STANDARD_UP),
    ("use_uv", STANDARD_UP),
]
