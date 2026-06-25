"""Profile tiers shared by per-stage registries.

`minimal` < `standard` < `strict`. A registry tags each plugin with the set of
tiers it runs in; the dispatcher skips a plugin when the active profile is not
in that set.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lib.config import Config

ALL: frozenset[str] = frozenset({"minimal", "standard", "strict"})
STANDARD_UP: frozenset[str] = frozenset({"standard", "strict"})

# Profile membership for hooks the per-stage dispatcher does not route. The
# dispatcher gates dispatched plugins via their `_registry.py` profile tags, but
# the Stop hooks (stop_phrase_guard, capture_followups) self-gate by calling
# `hook_enabled`, so their tier membership lives here.
HOOK_PROFILES: dict[str, frozenset[str]] = {
    "stop-phrase-guard": ALL,
    "capture-followups": STANDARD_UP,
}


def hook_enabled(hook_id: str, cfg: Config) -> bool:
    """Return whether a hook runs under the active profile and disabled set.

    Args:
        hook_id: The identifier of the hook to check.
        cfg: The resolved configuration containing profile and disabled hooks.

    Returns:
        True if the hook should run, False if disabled or excluded by profile.
    """
    if hook_id in cfg.disabled_hooks:
        return False
    return cfg.profile in HOOK_PROFILES.get(hook_id, ALL)
