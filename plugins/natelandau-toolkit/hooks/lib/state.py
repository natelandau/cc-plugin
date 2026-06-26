"""Session-keyed JSON state bridge for cheap cross-invocation hook state.

Some advisory hooks should not re-fire the same nudge every turn. Persisting a
small per-session record lets a hook suppress a message it has already shown.
The bridge is a JSON file under a per-user temp root, keyed by the payload's
`session_id`; it is read and written defensively so a hook never wedges a tool
call on a state error. Fail-open is the contract throughout: a read returns
`{}`, a write returns False, and `should_emit_once` returns True (emit) on any
failure, so a broken bridge degrades to "always show the nudge", never to a
swallowed tool call.

The bridge filename derives from `session_id`, which is untrusted, so the
resolved path is confined to the state root via `lib.paths.assert_within_root`
(defense in depth alongside sanitizing the id). The state root honors the
`NATELANDAU_TOOLKIT_STATE_DIR` environment variable so tests can isolate it
from the real temp directory; in normal operation it is unset.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

from lib.io import parse_json_object
from lib.paths import PathEscapeError, assert_within_root

# Env override for the state root, used by tests to isolate the bridge from the
# shared temp dir. Unset in normal operation.
STATE_DIR_ENV = "NATELANDAU_TOOLKIT_STATE_DIR"

# Subdirectory of the temp root that holds all bridge files, so containment has
# a dedicated trusted root rather than the whole temp dir.
_STATE_SUBDIR = "natelandau-toolkit"

# Upper bound on the bridge file we will read, mirroring the never-read-
# unbounded convention in lib.io. A session record is tiny; anything larger is
# corrupt and treated as empty.
MAX_STATE_BYTES = 256 * 1024

# Cap on the seen-signature list so a long session cannot grow the file without
# bound; oldest entries fall off first.
MAX_SEEN = 256

# Everything outside this set is stripped from a session id before it becomes a
# filename, so a crafted id cannot introduce path separators or traversal.
_UNSAFE_SESSION_CHARS = re.compile(r"[^A-Za-z0-9_-]+")
_MAX_SESSION_LEN = 128


def _state_root(root: Path | None) -> Path:
    """Resolve the directory that holds bridge files.

    Precedence: an explicit `root` (tests), then `NATELANDAU_TOOLKIT_STATE_DIR`,
    then a `natelandau-toolkit` subdir of the system temp directory.
    """
    if root is not None:
        return root
    env_root = os.environ.get(STATE_DIR_ENV)
    if env_root:
        return Path(env_root)
    return Path(tempfile.gettempdir()) / _STATE_SUBDIR


def _safe_session(session_id: str) -> str:
    """Reduce a session id to a filename-safe slug, or "" when nothing remains.

    Strips every character outside `[A-Za-z0-9_-]` so the result can never carry
    a path separator or `..`, and bounds the length. An id that sanitizes to
    empty yields "", which callers treat as "no session to key on". A non-string
    id (a malformed payload carrying a number or list) also yields "" rather
    than raising, keeping the fail-open contract for untrusted input.
    """
    if not isinstance(session_id, str):
        return ""
    return _UNSAFE_SESSION_CHARS.sub("", session_id)[:_MAX_SESSION_LEN]


def bridge_path(session_id: str, *, root: Path | None = None) -> Path | None:
    """Return the contained bridge-file path for a session, or None.

    Returns None when the session id sanitizes to empty, when canonicalizing the
    path fails (e.g. a symlink loop), or when the resolved path would escape the
    state root. A sanitized id cannot itself introduce `..` or a separator, but
    a pre-existing symlink at `<id>.json` could redirect the write outside the
    root, which `assert_within_root` catches; this is the case it guards.
    """
    safe = _safe_session(session_id)
    if not safe:
        return None
    state_root = _state_root(root)
    candidate = state_root / f"{safe}.json"
    try:
        return assert_within_root(candidate, state_root, action="write")
    except PathEscapeError, OSError:
        return None


def read_state(session_id: str, *, root: Path | None = None) -> dict[str, object]:
    """Read a session's bridge record, returning {} on any failure.

    A missing, oversized, malformed, or non-object bridge file all yield {} so
    the caller fails open.
    """
    path = bridge_path(session_id, root=root)
    if path is None:
        return {}
    try:
        # Read bounded, like lib.io reads stdin: a corrupt or oversized bridge
        # file (anything past MAX_STATE_BYTES) is rejected without slurping it
        # all into memory first. UnicodeDecodeError (a ValueError, not an
        # OSError) is caught so non-UTF-8 bytes fail open rather than raising.
        with path.open("r", encoding="utf-8") as fh:
            raw = fh.read(MAX_STATE_BYTES + 1)
    except OSError, UnicodeDecodeError:
        return {}
    if len(raw) > MAX_STATE_BYTES:
        return {}
    return parse_json_object(raw)


def write_state(session_id: str, data: dict[str, object], *, root: Path | None = None) -> bool:
    """Atomically write a session's bridge record, returning success.

    Writes to a temp file in the state root and renames it over the target so a
    concurrent reader never sees a half-written file. Any failure (unresolvable
    path, unwritable dir, serialization error) returns False without raising,
    honoring the never-wedge contract.
    """
    path = bridge_path(session_id, root=root)
    if path is None:
        return False
    # Bind the temp path before writing so a json.dump failure (disk full, or a
    # non-serializable record from a future caller) can still clean up the
    # delete=False temp file rather than leaving an orphan in the state dir.
    tmp: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=str(path.parent),
            prefix=".tmp-",
            suffix=".json",
            delete=False,
        ) as fh:
            tmp = Path(fh.name)
            json.dump(data, fh)
    except OSError, TypeError, ValueError:
        if tmp is not None:
            tmp.unlink(missing_ok=True)
        return False
    try:
        tmp.replace(path)
    except OSError:
        tmp.unlink(missing_ok=True)
        return False
    return True


def should_emit_once(session_id: str, signature: str, *, root: Path | None = None) -> bool:
    """Return whether an advisory keyed by `signature` should fire this session.

    The first time a `(session_id, signature)` pair is seen it returns True and
    records the signature; afterward it returns False so the nudge is shown once
    per session rather than every turn. Returns True (never suppress) when there
    is no session id or no signature to key on, and on any state failure, so the
    debounce can only ever quiet a duplicate, never silence a first occurrence.
    """
    if not session_id or not signature:
        return True
    state = read_state(session_id, root=root)
    raw_seen = state.get("seen")
    seen = [s for s in raw_seen if isinstance(s, str)] if isinstance(raw_seen, list) else []
    if signature in seen:
        return False
    seen.append(signature)
    write_state(session_id, {"seen": seen[-MAX_SEEN:]}, root=root)
    return True
