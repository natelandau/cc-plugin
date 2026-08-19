"""Shared environment scrubbing for subprocess-based hook tests.

Recall's `project_root` resolves a project by running `git rev-parse` with the
env it is handed, and the branch-protection hook resolves a branch the same
way, so any git-prefixed env var present in that env can retarget git at a
different repository than the test's own cwd (GIT_DIR and GIT_WORK_TREE most
directly, but also GIT_NAMESPACE and the GIT_CONFIG_PARAMETERS /
GIT_CONFIG_COUNT / GIT_CONFIG_KEY_<n> / GIT_CONFIG_VALUE_<n> family, through
which a config override such as core.worktree has the same effect). The
indexed GIT_CONFIG_KEY_<n>/GIT_CONFIG_VALUE_<n> names can't be enumerated as a
fixed set, so a prefix match is the only rule that actually covers the
hazard. That makes the rule deliberately broader than "location": every
GIT_-prefixed var goes, including ones that only affect behavior, because
there is no way to keep those and still catch the indexed family.
When the suite runs under a git hook (pre-commit) or from a worktree,
git exports these vars and they leak into every test-spawned process, making
a tmp project resolve to the outer checkout instead. Strip them so resolution
falls through to the test's own cwd / CLAUDE_PROJECT_DIR, matching production
where a hook runs with no git-hook env.

The toolkit's exempt-paths variable goes for a related reason: it waives branch
and commit-message enforcement for everything inside the trees it names, so a
developer who exports it would otherwise have their real directories decide
whether a test's payload is exempt. Tests that exercise the carve-out set it
back explicitly with `exempt_env`.
"""

from __future__ import annotations

import os

# Prefix for every env var git uses to locate or override a repository.
_GIT_VAR_PREFIX = "GIT_"

# The exempt-paths variable, spelled out rather than imported from the hook
# package: `tests/_env` is imported at collection time, before any fixture has
# put the hooks dir on sys.path.
EXEMPT_PATHS_VAR = "NATELANDAU_TOOLKIT_EXEMPT_PATHS"

# Non-git vars that likewise retarget a hook away from the test's own fixtures.
_AMBIENT_VARS = frozenset({EXEMPT_PATHS_VAR})


def exempt_env(*roots: str) -> dict[str, str]:
    """Return env overrides declaring each of `roots` an exempt tree."""
    return {EXEMPT_PATHS_VAR: os.pathsep.join(roots)}


def clean_environ(*, also_drop: frozenset[str] = frozenset()) -> dict[str, str]:
    """Copy os.environ with every GIT_ var, the ambient vars, and `also_drop` keys removed.

    Use for any env handed to a hook subprocess or to `Store.for_cwd` so git
    resolution targets the test's tmp project rather than the checkout the suite
    happens to run from.
    """
    dropped = _AMBIENT_VARS | also_drop
    return {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(_GIT_VAR_PREFIX) and k not in dropped
    }
