"""Symlink-escape-hardened path containment for hooks that derive write targets.

A hook that writes under a root computed from untrusted input (e.g. the
session-keyed state bridge, whose filename derives from the payload's
`session_id`) must confirm the destination stays inside that root. A plain
`resolve()` plus membership test can be defeated two ways: an intermediate
directory may be a symlink pointing out of the root, or the target may not
exist yet so there is nothing to canonicalize.

`realpath_nearest_existing` closes both gaps: it canonicalizes the nearest
*existing* ancestor (resolving its symlinks) and re-appends the not-yet-created
tail lexically, so a symlinked intermediate is resolved while a missing leaf is
still placed correctly. `assert_within_root` is the fail-closed guard built on
it. Adapted from the containment approach in the ECC reference plugin.
"""

from __future__ import annotations

from pathlib import Path


class PathEscapeError(ValueError):
    """A target path resolved outside its trusted root."""


def realpath_nearest_existing(target: Path) -> Path:
    """Canonicalize `target`, resolving symlinks across its existing prefix.

    Walk up to the nearest ancestor that exists, resolve that ancestor
    (following symlinks), then re-append the missing tail components lexically.
    A target that does not exist yet is canonicalized without inventing it, and
    a symlinked intermediate directory is resolved rather than trusted, which
    defeats escapes through a symlink that points out of an intended root.
    Relative targets are anchored to the current working directory first.
    """
    current = target if target.is_absolute() else Path.cwd() / target
    tail: list[str] = []
    # `exists()` follows symlinks, so a broken symlink is treated as missing
    # and its name handled lexically rather than followed off the root.
    while not current.exists():
        parent = current.parent
        if parent == current:  # reached the filesystem root
            break
        tail.append(current.name)
        current = parent
    real = current.resolve()
    for name in reversed(tail):
        real = real / name
    return real


def _contains(real_root: Path, real_target: Path) -> bool:
    """Return whether already-canonicalized `real_target` is at or under `real_root`."""
    return real_target == real_root or real_root in real_target.parents


def is_within_root(target: Path, root: Path) -> bool:
    """Return whether `target` resolves to `root` itself or a path beneath it.

    Symlinks are resolved on both sides via `realpath_nearest_existing`, so an
    intermediate symlink cannot smuggle the target outside `root`.
    """
    return _contains(realpath_nearest_existing(root), realpath_nearest_existing(target))


def assert_within_root(target: Path, root: Path, *, action: str = "write") -> Path:
    """Return the canonicalized `target`, or raise if it escapes `root`.

    The fail-closed guard for any hook that writes under a derived root: it
    refuses, rather than silently proceeding, when the resolved destination is
    not contained in the resolved root.

    Args:
        target: The path about to be written, possibly not yet existing.
        root: The trusted directory the write must stay within.
        action: Verb used in the error message (e.g. "write", "read").

    Returns:
        The canonicalized, contained target path.

    Raises:
        PathEscapeError: If `target` resolves outside `root`.
    """
    real_root = realpath_nearest_existing(root)
    real_target = realpath_nearest_existing(target)
    if not _contains(real_root, real_target):
        msg = f"refusing to {action} outside {root}: {target} escapes the trusted root"
        raise PathEscapeError(msg)
    return real_target
