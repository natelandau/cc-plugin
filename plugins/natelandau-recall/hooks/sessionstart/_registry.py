"""Plugins for this stage, in run order. Empty list => the stage is a noop."""

from __future__ import annotations

from lib.profiles import ALL

PLUGINS: list[tuple[str, frozenset[str]]] = [
    ("inject_memory", ALL),
]
