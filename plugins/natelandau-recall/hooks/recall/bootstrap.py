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
from pathlib import Path
from typing import TYPE_CHECKING

from recall import transcript
from recall.paths import is_within_root
from recall.safety import scrub

if TYPE_CHECKING:
    from collections.abc import Sequence

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

    def _staged_session_ids(self) -> set[str]:
        """Return stems of all staged session scratch files in the bootstrap dir.

        Fails open: returns an empty set if the directory is missing or unreadable
        so callers never raise when the bootstrap dir was never created.
        """
        try:
            return {p.stem for p in self.store.bootstrap_dir.glob("*.json")}
        except OSError:
            return set()

    def apply(self, plan: dict[str, object]) -> dict[str, object]:
        """Write an approved merge plan to the store under containment + scrub; never raises.

        Every learning and the backlog body is path-contained to the store and
        secret-scrubbed before write, the same backstop the live sweep applies to
        its agent's writes. Ledgers ALL staged sessions (every *.json scratch file
        in the bootstrap dir), so a session that produced no memory is still marked
        processed and skipped on future runs. Also ledgers any extra session ids
        supplied in the plan's ``processed_session_ids`` list.

        Args:
            plan: Dict with keys ``learnings`` (list of filename/content dicts),
                ``backlog`` (str or None), and ``processed_session_ids`` (list of str).

        Returns:
            Dict with keys ``written`` (paths written), ``rejected`` (paths blocked),
            ``redacted`` (paths whose content was scrubbed), and ``ledger_added``
            (count of session ids newly added to the ledger by this call).
        """
        written: list[str] = []
        rejected: list[str] = []
        redacted: list[str] = []

        learnings = plan.get("learnings")
        if isinstance(learnings, list):
            self._write_learnings(learnings, written, rejected, redacted)

        backlog = plan.get("backlog")
        if isinstance(backlog, str):
            self._write_one(self.store.backlog_path, backlog, written, rejected, redacted)

        # Union of staged scratch files (deterministic) + plan ids (backward compat).
        before = self.store.read_processed()
        all_ids: set[str] = self._staged_session_ids()
        ids = plan.get("processed_session_ids")
        if isinstance(ids, list):
            for sid in ids:
                if isinstance(sid, str) and sid:
                    all_ids.add(sid)
        for sid in all_ids:
            self.store.add_processed(sid)
        added = len(all_ids - before)

        return {
            "written": written,
            "rejected": rejected,
            "redacted": redacted,
            "ledger_added": added,
        }

    def _write_learnings(
        self,
        learnings: Sequence[object],
        written: list[str],
        rejected: list[str],
        redacted: list[str],
    ) -> None:
        """Write each learning file op, contained to the learnings dir.

        Args:
            learnings: List of dicts with ``filename`` and ``content`` keys.
            written: Accumulator for successfully written paths.
            rejected: Accumulator for blocked paths.
            redacted: Accumulator for paths whose content was scrubbed.
        """
        for op in learnings:
            if not isinstance(op, dict):
                continue
            filename = op.get("filename")
            content = op.get("content")
            if not isinstance(filename, str) or not isinstance(content, str):
                continue
            # Reject non-bare basenames before touching the filesystem so that
            # traversal attempts like "../escape.md" or "/etc/passwd" fail early,
            # independent of filesystem state.
            if "/" in filename or filename in ("", ".", "..") or Path(filename).is_absolute():
                rejected.append(filename)
                continue
            # Resolve to normalize any .. traversal before the containment check so
            # a filename like "../escape.md" is caught even when learnings_dir is new.
            target = (self.store.learnings_dir / filename).resolve()
            if not is_within_root(target, self.store.learnings_dir):
                rejected.append(str(target))
                continue
            self._write_one(target, content, written, rejected, redacted)

    def _write_one(
        self,
        target: Path,
        content: str,
        written: list[str],
        rejected: list[str],
        redacted: list[str],
    ) -> None:
        """Contain, scrub, and write one file; record the outcome. Never raises.

        Args:
            target: Absolute path where the file should be written.
            content: Text content to write (will be scrubbed before write).
            written: Accumulator for successfully written paths.
            rejected: Accumulator for blocked or failed paths.
            redacted: Accumulator for paths whose content was scrubbed.
        """
        # Load-bearing: catches a symlinked learnings_dir that the learnings_dir-level
        # containment check would miss; do not remove this backstop during refactors.
        if not is_within_root(target, self.store.data_dir):
            rejected.append(str(target))
            return
        scrubbed, changed = scrub(content)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(scrubbed, encoding="utf-8")
        except OSError as exc:
            rejected.append(f"{target} ({exc})")
        else:
            if changed:
                redacted.append(str(target))
            written.append(str(target))
