#!/usr/bin/env -S uv run --script

# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///

"""Print an absolute path inside the current project's recall store.

The sole shell-facing facade over `Store`: skills call this to locate the store
instead of re-deriving the dash-encoded project key in prose, so the encoding
lives in exactly one place (`recall/paths.py`). The project is resolved the same
way every hook resolves it (git common-dir -> CLAUDE_PROJECT_DIR -> cwd).

Read-only and pure: it computes a path and prints it, never creating or touching
anything, so callers stay responsible for the "does it exist yet?" question.

    recall-path.py --data-dir     # the store root
    recall-path.py --handoff      # <data-dir>/HANDOFF.md
    recall-path.py --backlog      # <data-dir>/backlog.md
    recall-path.py --learnings    # <data-dir>/learnings/

Exactly one flag per call; anything else is a usage error (non-zero exit).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

HOOKS_ROOT = Path(__file__).resolve().parent
if str(HOOKS_ROOT) not in sys.path:
    sys.path.insert(0, str(HOOKS_ROOT))

from recall.store import Store  # noqa: E402


def main() -> None:
    """Resolve the requested store path for the current directory and print it."""
    parser = argparse.ArgumentParser(description="Resolve a recall store path.")
    target = parser.add_mutually_exclusive_group(required=True)
    # Each flag's const is the Store attribute that yields its path, so resolution
    # is a single getattr with no flag-to-attribute lookup table to keep in sync.
    target.add_argument("--data-dir", action="store_const", const="data_dir", dest="target")
    target.add_argument("--handoff", action="store_const", const="handoff_path", dest="target")
    target.add_argument("--backlog", action="store_const", const="backlog_path", dest="target")
    target.add_argument("--learnings", action="store_const", const="learnings_dir", dest="target")
    args = parser.parse_args()

    store = Store.for_cwd(cwd=Path.cwd(), env=os.environ)
    print(getattr(store, args.target))  # noqa: T201


if __name__ == "__main__":
    main()
