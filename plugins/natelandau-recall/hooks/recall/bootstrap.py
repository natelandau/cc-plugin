"""Backfill the recall memory store from a project's past Claude Code transcripts.

The live sweep captures memory at session boundaries; a project that adopts
recall after the fact starts empty. This engine discovers past transcripts for
the current project, parses each through the same noise filter the sweep uses
(`transcript.meaningful_text`), selects which are worth mining, stages them to
scratch files for extractor subagents, and applies a user-approved merge plan
through the same path-containment + secret-scrub backstop the sweep trusts.

Deterministic helpers are module-level so they unit-test without a subprocess;
`Bootstrap` is the thin coordinator the CLI facade drives.
"""

from __future__ import annotations

import re
from pathlib import Path  # noqa: TC003

# A transcript whose first user message starts like the sweep prompt is the
# headless sweeper's own run (`claude -p` persists these); never mine them.
SWEEP_SIGNATURE = "You are the project-memory sweeper"

# Claude Code names ~/.claude/projects/<dir> by replacing every character of the
# launch cwd that is not [A-Za-z0-9-] with a dash (the leading slash included,
# dots and spaces too). This is NOT the recall store key (`encode_project_key`),
# which drops the leading slash; verified empirically against real project dirs.
_DIRNAME_DISALLOWED = re.compile(r"[^A-Za-z0-9-]")


def claude_project_dir_name(cwd: Path) -> str:
    """Encode a launch cwd into its ~/.claude/projects directory name."""
    return _DIRNAME_DISALLOWED.sub("-", str(cwd))


def transcripts_dir_for(cwd: Path, *, home: Path) -> Path:
    """Return the ~/.claude/projects dir holding `cwd`'s transcripts (not created)."""
    return home / ".claude" / "projects" / claude_project_dir_name(cwd)


def list_transcripts(tdir: Path) -> list[Path]:
    """Return the dir's *.jsonl transcripts sorted oldest-first by mtime.

    Returns [] for a missing/unreadable dir so callers fail open.
    """
    try:
        files = list(tdir.glob("*.jsonl"))
    except OSError:
        return []
    return sorted(files, key=lambda p: p.stat().st_mtime)


def session_id_of(path: Path) -> str:
    """Return the session id (the transcript filename without .jsonl)."""
    return path.stem


def is_sweep_transcript(parsed: list[dict[str, str]]) -> bool:
    """Return whether a parsed transcript is one of the headless sweeper's own runs."""
    for message in parsed:
        if message.get("role") == "user":
            return SWEEP_SIGNATURE in message.get("text", "")
    return False
