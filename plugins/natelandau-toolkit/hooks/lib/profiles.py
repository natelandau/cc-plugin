"""Profile tiers shared by per-stage registries.

`minimal` < `standard` < `strict`. A registry tags each plugin with the set of
tiers it runs in; the dispatcher skips a plugin when the active profile is not
in that set.
"""

from __future__ import annotations

ALL: frozenset[str] = frozenset({"minimal", "standard", "strict"})
STANDARD_UP: frozenset[str] = frozenset({"standard", "strict"})
