"""Resolve the directory trees that are exempt from the project conventions.

Some trees are working stores committed to on their default branch by design.
A path inside one skips `branch-protection`'s protected-branch checks and the
`commit-message` hook, and nothing more -- destructive commands are judged the
same everywhere, since a force push destroys work whatever directory it runs in.

Two sources, unioned, both owned by the user rather than by this plugin:

- `exempt_paths` in the GLOBAL `~/.claude/natelandau-toolkit.toml`, arriving as
  `Config.exempt_paths`. The project layer is deliberately not consulted; see
  `lib.config`.
- `$NATELANDAU_TOOLKIT_EXEMPT_PATHS`, a `os.pathsep`-separated list, for roots
  that differ per machine or are composed from another variable.

An entry that cannot name one directory tree -- empty, relative, unexpandable
(`~nosuchuser`), the filesystem root, or any path carrying a `..` segment -- is
dropped on its own, leaving its neighbors intact, so a typo narrows the
exemption rather than widening it or voiding the whole list.
Exemption is keyed off the path an action touches rather than the shell's cwd,
matching how the branch guard already decides everything else.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from lib.paths import expand_user, is_within_root

if TYPE_CHECKING:
    from collections.abc import Sequence

ENV_VAR = "NATELANDAU_TOOLKIT_EXEMPT_PATHS"


@dataclass(frozen=True, slots=True)
class ExemptRoots:
    """The exempt directory trees resolved once for one hook invocation.

    Resolved up front and passed down rather than re-read per check, so every
    guard in one evaluation answers against the same set.
    """

    roots: tuple[Path, ...] = ()

    def contains(self, path: str, cwd: str = "") -> bool:
        """Return whether `path` names an exempt root or something inside one.

        A relative `path` is anchored to `cwd` when one is given. Symlinks are
        resolved on both sides, so a link into an exempt tree is exempt and a
        link out of one is not. Returns False when nothing is configured, which
        keeps the whole lookup off the hot path for anyone who exempts nothing.
        """
        if not self.roots or not path:
            return False
        target = expand_user(path)
        if not target.is_absolute() and cwd:
            target = Path(cwd) / target
        return any(is_within_root(target, root) for root in self.roots)


def _usable_root(raw: str) -> Path | None:
    """Return `raw` as an exempt root, or None when it cannot name one tree."""
    stripped = raw.strip()
    if not stripped:
        return None
    path = expand_user(stripped)
    # A relative root has no fixed meaning across the cwds one hook process
    # sees, and `/` would exempt every path on the machine. A `..` segment is
    # rejected rather than collapsed: it lets an entry spell the filesystem
    # root the long way (`/..`), and the safe reading of an ambiguous root is
    # no root at all.
    if not path.is_absolute() or path == Path(path.root) or ".." in path.parts:
        return None
    return path


def resolve(configured: Sequence[str] = ()) -> ExemptRoots:
    """Resolve the exempt roots from `configured` (the global config) and the environment."""
    from_env = os.environ.get(ENV_VAR, "").split(os.pathsep)
    entries = [*configured, *from_env]
    return ExemptRoots(tuple(root for root in map(_usable_root, entries) if root is not None))
