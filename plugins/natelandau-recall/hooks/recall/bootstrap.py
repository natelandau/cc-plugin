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

import json
import re
from dataclasses import dataclass
from pathlib import Path  # noqa: TC003
from typing import TYPE_CHECKING

from recall import transcript

if TYPE_CHECKING:
    from recall.config import RecallConfig
    from recall.store import Store

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


DEFAULT_LIMIT = 20


@dataclass(frozen=True, slots=True)
class _Candidate:
    """A transcript that passed parsing, with the data the manifest needs."""

    session_id: str
    parsed: list[dict[str, str]]
    mtime: float


class Bootstrap:
    """Discover, stage, and apply project-memory backfill from past transcripts."""

    def __init__(self, store: Store, config: RecallConfig, *, home: Path, cwd: Path) -> None:
        self.store = store
        self.config = config
        self.home = home
        self.cwd = cwd

    def discover(
        self, *, limit: int | None, exclude_session: str | None = None
    ) -> list[dict[str, object]]:
        """Stage eligible past transcripts to scratch files and return the manifest.

        Filters out the live session (the newest transcript, still being written),
        the headless sweeper's own runs, sessions below `min_exchanges`, and any
        session already in the processed ledger. Keeps the most recent `limit`
        (all when None) and returns them oldest-first so the merge sees memory
        accrue chronologically.
        """
        tdir = transcripts_dir_for(self.cwd, home=self.home)
        files = list_transcripts(tdir)
        if not files:
            return []
        live = exclude_session or session_id_of(files[-1])
        processed = self.store.read_processed()

        candidates: list[_Candidate] = []
        for path in files:
            sid = session_id_of(path)
            if sid == live or sid in processed:
                continue
            parsed = transcript.meaningful_text(transcript.read_entries(str(path)))
            if len(parsed) < self.config.min_exchanges:
                continue
            if is_sweep_transcript(parsed):
                continue
            candidates.append(_Candidate(session_id=sid, parsed=parsed, mtime=path.stat().st_mtime))

        if limit is not None:
            candidates = candidates[-limit:]
        return [self._stage(c) for c in candidates]

    def _stage(self, candidate: _Candidate) -> dict[str, object]:
        """Write one candidate's parsed transcript to a scratch file; return its manifest entry."""
        self.store.bootstrap_dir.mkdir(parents=True, exist_ok=True)
        scratch = self.store.bootstrap_dir / f"{candidate.session_id}.json"
        scratch.write_text(json.dumps(candidate.parsed, ensure_ascii=False), encoding="utf-8")
        return {
            "session_id": candidate.session_id,
            "scratch_path": str(scratch),
            "exchange_count": len(candidate.parsed),
            "mtime": candidate.mtime,
        }
