"""Shared environment scrubbing for subprocess-based hook tests.

Recall's `project_root` resolves a project by running `git rev-parse` with the
env it is handed, and the branch-protection hook resolves a branch the same
way, so any git location vars (GIT_DIR, GIT_WORK_TREE, ...) present in that env
pin resolution to whatever repo they name. When the suite runs under a git hook
(pre-commit) or from a worktree, git exports those vars and they leak into every
test-spawned process, making a tmp project resolve to the outer checkout
instead. Strip them so resolution falls through to the test's own cwd /
CLAUDE_PROJECT_DIR, matching production where a hook runs with no git-hook env.
"""

from __future__ import annotations

import os

# Git env vars that pin git to a specific repository location.
GIT_REPO_VARS = frozenset(
    {
        "GIT_DIR",
        "GIT_COMMON_DIR",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_WORK_TREE",
    }
)


def clean_environ(*, also_drop: frozenset[str] = frozenset()) -> dict[str, str]:
    """Copy os.environ with the git-repo vars (and any `also_drop` keys) removed.

    Use for any env handed to a hook subprocess or to `Store.for_cwd` so git
    resolution targets the test's tmp project rather than the checkout the suite
    happens to run from.
    """
    skip = GIT_REPO_VARS | also_drop
    return {k: v for k, v in os.environ.items() if k not in skip}
