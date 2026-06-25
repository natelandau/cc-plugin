"""Plugins for this stage, in run order. Empty list => the stage is a noop."""

from __future__ import annotations

from lib.profiles import ALL, STANDARD_UP

PLUGINS: list[tuple[str, frozenset[str]]] = [
    ("stop_phrase_guard", ALL),
    ("capture_followups", STANDARD_UP),
]
