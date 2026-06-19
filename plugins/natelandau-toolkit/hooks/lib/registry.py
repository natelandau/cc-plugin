# plugins/natelandau-toolkit/hooks/lib/registry.py
"""Wiring for PreToolUse checks: profile tiers, tool routing, gating.

Imports each hook module's evaluate() and declares, in safety-first
order, which tool names each check applies to and which profile tiers
include it. Blocking safety checks run in every tier; advisory checks are
standard-and-up.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import enforce_branch_protection
import enforce_commit_message
import protect_secrets
import protect_system
import use_uv

if TYPE_CHECKING:
    from collections.abc import Callable

    from lib.config import Config
    from lib.io import Decision

ALL: frozenset[str] = frozenset({"minimal", "standard", "strict"})
STANDARD_UP: frozenset[str] = frozenset({"standard", "strict"})

HOOK_PROFILES: dict[str, frozenset[str]] = {
    "branch-protection": ALL,
    "protect-secrets": ALL,
    "protect-system": ALL,
    "commit-message": STANDARD_UP,
    "use-uv": STANDARD_UP,
    "stop-phrase-guard": ALL,
}


@dataclass(frozen=True, slots=True)
class Check:
    """A PreToolUse check: its id, evaluator, and the tools it applies to."""

    id: str
    evaluate: Callable[[dict[str, Any], Config], Decision | None]
    tools: frozenset[str]


# Safety-first order: blocking checks before advisory ones.
PRE_TOOL_CHECKS: tuple[Check, ...] = (
    Check(
        "branch-protection",
        enforce_branch_protection.evaluate,
        frozenset({"Edit", "Write", "NotebookEdit", "Bash"}),
    ),
    Check(
        "protect-secrets",
        protect_secrets.evaluate,
        frozenset({"Read", "Edit", "Write", "Bash"}),
    ),
    Check("protect-system", protect_system.evaluate, frozenset({"Bash"})),
    Check("commit-message", enforce_commit_message.evaluate, frozenset({"Bash"})),
    Check("use-uv", use_uv.evaluate, frozenset({"Bash"})),
)


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


def applicable_checks(tool_name: str, cfg: Config) -> list[Check]:
    """Return the ordered checks that apply to tool_name and are enabled.

    Args:
        tool_name: The Claude tool being invoked (e.g. "Bash", "Read").
        cfg: The resolved configuration to gate checks against.

    Returns:
        Ordered list of checks whose tool set includes tool_name and that are
        enabled under the active profile.
    """
    return [
        check
        for check in PRE_TOOL_CHECKS
        if tool_name in check.tools and hook_enabled(check.id, cfg)
    ]
