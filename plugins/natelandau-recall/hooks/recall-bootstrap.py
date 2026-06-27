#!/usr/bin/env -S uv run --script

# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///

"""Drive the recall bootstrap engine from skills: discover, apply, clean.

The shell-facing facade over `recall.bootstrap.Bootstrap`, paired with
`recall-path.py`. `discover` stages eligible past transcripts and prints a JSON
manifest the skill fans out to extractor subagents; `apply` writes a merged,
user-approved plan under the store's containment + scrub backstop; `clean`
removes the scratch staging dir. Read-only except for `apply` (writes the store)
and `clean` (removes scratch).

    recall-bootstrap.py discover [--limit N | --all]
    recall-bootstrap.py apply <plan-file>
    recall-bootstrap.py clean
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

HOOKS_ROOT = Path(__file__).resolve().parent
if str(HOOKS_ROOT) not in sys.path:
    sys.path.insert(0, str(HOOKS_ROOT))

from recall.bootstrap import DEFAULT_LIMIT, Bootstrap  # noqa: E402
from recall.config import RecallConfig  # noqa: E402
from recall.store import Store  # noqa: E402


def _build() -> Bootstrap:
    """Construct a Bootstrap for the current project from the environment."""
    cwd = Path.cwd()
    store = Store.for_cwd(cwd=cwd, env=os.environ)
    config = RecallConfig.load(project_dir=os.environ.get("CLAUDE_PROJECT_DIR"))
    return Bootstrap(store=store, config=config, home=Path.home(), cwd=cwd)


def _cmd_discover(args: argparse.Namespace) -> None:
    """Print the JSON manifest of staged transcripts."""
    limit = None if args.all else args.limit
    manifest = _build().discover(limit=limit)
    print(json.dumps(manifest, ensure_ascii=False))  # noqa: T201


def _cmd_apply(args: argparse.Namespace) -> None:
    """Apply a merge plan file and print the JSON result summary."""
    plan = json.loads(Path(args.plan_file).read_text(encoding="utf-8"))
    result = _build().apply(plan)
    print(json.dumps(result, ensure_ascii=False))  # noqa: T201


def _cmd_clean(_: argparse.Namespace) -> None:
    """Remove the bootstrap scratch dir; best-effort."""
    shutil.rmtree(_build().store.bootstrap_dir, ignore_errors=True)


def main() -> None:
    """Parse the subcommand and dispatch."""
    parser = argparse.ArgumentParser(description="Backfill recall memory from past transcripts.")
    sub = parser.add_subparsers(dest="command", required=True)

    discover = sub.add_parser("discover", help="stage past transcripts; print manifest JSON")
    group = discover.add_mutually_exclusive_group()
    group.add_argument(
        "--limit", type=int, default=DEFAULT_LIMIT, help="most-recent N (default 20)"
    )
    group.add_argument("--all", action="store_true", help="process all eligible transcripts")
    discover.set_defaults(func=_cmd_discover)

    apply_p = sub.add_parser("apply", help="write an approved merge plan")
    apply_p.add_argument("plan_file", help="path to the plan JSON file")
    apply_p.set_defaults(func=_cmd_apply)

    clean = sub.add_parser("clean", help="remove the scratch staging dir")
    clean.set_defaults(func=_cmd_clean)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
