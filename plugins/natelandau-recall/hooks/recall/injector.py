"""Render the SessionStart memory injection from a project's store.

Read side only: assembles the learnings index (one line per file, bodies
omitted) and a one-line backlog pointer (a count of open items plus a nudge to
run the triage skill), wraps them under a fixed preamble in
`<recall-memory>…</recall-memory>`, and returns "" when the store is empty. The
backlog body is never injected: triaging it is the `/recall-backlog` skill's job,
so the session only needs to know it exists. Every file read fails open so one
unreadable artifact never wedges the whole injection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from recall import frontmatter

if TYPE_CHECKING:
    from recall.config import RecallConfig
    from recall.store import Store

PREAMBLE = (
    "This project has persisted memory (learnings and a deferred backlog). "
    "Consult it before assuming; read a learning file when its 'read when' hint matches "
    "your task. New memory is recorded automatically at session end — do not capture inline."
)


class Injector:
    """Builds the SessionStart injection block from a store and config."""

    def __init__(self, store: Store, config: RecallConfig) -> None:
        self.store = store
        self.config = config

    def build(self) -> str:
        """Assemble the full wrapped injection, or "" when the store has nothing to show."""
        index = self._learnings_index()
        backlog = self._backlog_pointer()
        if not any([index, backlog]):
            return ""

        parts: list[str] = [PREAMBLE]
        if index:
            parts.append(f"## Learnings Index\n{index}")
        if backlog:
            parts.append(backlog)
        return f"<recall-memory>\n{'\n\n'.join(parts)}\n</recall-memory>"

    def _learnings_index(self) -> str:
        """Return one index line per learning: relative path, summary, read-when hint."""
        items = frontmatter.scan_learnings(self.store.learnings_dir)
        if not items:
            return ""
        lines: list[str] = []
        for path, summary, read_when in items:
            rel = path.relative_to(self.store.data_dir)
            line = f"- {rel} — {summary}"
            if read_when:
                line += f"\n  read when: {'; '.join(read_when)}"
            lines.append(line)
        return "\n".join(lines)

    def _backlog_pointer(self) -> str:
        """Return a one-line "N open items, run the triage skill" pointer, or "".

        Counts every open (`- [ ]`) item regardless of section so the count
        matches what `/recall-backlog` would actually collect, and surfaces only
        the count and the skill nudge. The body stays out of context: it is the
        skill's to triage, not the session's to carry.
        """
        backlog = self.store.backlog_path
        if not backlog.exists():
            return ""
        try:
            text = backlog.read_text(encoding="utf-8")
        except OSError:
            return ""  # fail open: skip just this block

        open_items = sum(1 for line in text.splitlines() if line.startswith("- [ ]"))
        if not open_items:
            return ""
        noun = "item" if open_items == 1 else "items"
        return f"{open_items} {noun} in the deferred backlog. Run /recall-backlog to triage."
