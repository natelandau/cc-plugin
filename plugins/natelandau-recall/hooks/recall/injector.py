"""Render the SessionStart memory injection from a project's store.

Read side only: assembles the architecture block (capped, never silently
truncated), the learnings index (one line per file, bodies omitted), and the
backlog summary (counts per type plus inline `[S]` quick-wins), wraps them under
a fixed preamble in `<recall-memory>…</recall-memory>`, and returns "" when the
store is empty. Every file read fails open so one unreadable artifact never
wedges the whole injection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from recall import frontmatter

if TYPE_CHECKING:
    from recall.config import RecallConfig
    from recall.store import Store

PREAMBLE = (
    "This project has persisted memory (learnings, deferred backlog, architecture). "
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
        arch = self._architecture_block()
        index = self._learnings_index()
        backlog = self._backlog_summary()
        if not any([arch, index, backlog]):
            return ""

        parts: list[str] = [PREAMBLE]
        if arch:
            parts.append(f"## Architecture\n{arch}")
        if index:
            parts.append(f"## Learnings Index\n{index}")
        if backlog:
            parts.append(f"## Backlog\n{backlog}")
        return f"<recall-memory>\n{'\n\n'.join(parts)}\n</recall-memory>"

    def _architecture_block(self) -> str:
        """Return architecture.md, capped with an explicit (non-silent) truncation note."""
        arch = self.store.architecture_path
        if not arch.exists():
            return ""
        try:
            raw = arch.read_bytes()
        except OSError:
            return ""  # fail open: skip just this block
        max_bytes = self.config.architecture_max_bytes
        if len(raw) <= max_bytes:
            return raw.decode("utf-8", errors="replace")
        truncated = raw[:max_bytes].decode("utf-8", errors="replace")
        return (
            truncated
            + f"\n\n[architecture.md truncated at {max_bytes} bytes — run /review-memory to trim]"
        )

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

    def _backlog_summary(self) -> str:
        """Return a count-per-type summary plus inline open `[S]` quick-win lines."""
        backlog = self.store.backlog_path
        if not backlog.exists():
            return ""
        try:
            text = backlog.read_text(encoding="utf-8")
        except OSError:
            return ""  # fail open: skip just this block

        current_section: str | None = None
        counts: dict[str, int] = {}
        quick_wins: list[str] = []
        for line in text.splitlines():
            if line.startswith("## "):
                # A blank header ("## ") leaves current_section None so orphans are ignored.
                current_section = line[3:].strip() or None
            elif line.startswith("- [ ]") and current_section is not None:
                counts[current_section] = counts.get(current_section, 0) + 1
                if "[S]" in line:
                    # Strip "- [ ] [S] " prefix and trailing date (" — YYYY-MM-DD").
                    item_text = line[len("- [ ]") :].strip().replace("[S]", "", 1).strip()
                    if " — " in item_text:
                        item_text = item_text[: item_text.rfind(" — ")].strip()
                    quick_wins.append(item_text)

        if not counts:
            return ""
        total = sum(counts.values())
        count_parts = " / ".join(f"{v} {k}" for k, v in counts.items())
        result = f"{total} deferred: {count_parts}"
        for qw in quick_wins:
            result += f"\n  [S] {qw}"
        return result
