"""Assemble the injected memory blocks for the SessionStart hook.

Provides four pure helpers that read from the project data directory and
return formatted strings ready for injection. Callers that need the full
XML-wrapped payload should use `build_injection`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from lib import frontmatter, store

if TYPE_CHECKING:
    from pathlib import Path

PREAMBLE = (
    "This project has persisted memory (learnings, deferred backlog, architecture). "
    "Consult it before assuming; read a learning file when its 'read when' hint matches "
    "your task. New memory is recorded automatically at session end — do not capture inline."
)


def architecture_block(data: Path, *, max_bytes: int) -> str:
    """Return the architecture.md content, capped at `max_bytes` with an explicit note.

    Never silently truncates: when the file exceeds the cap the returned string
    ends with a visible `[architecture.md truncated …]` marker so the model knows
    the view is incomplete.

    Args:
        data: Project data directory that may contain `architecture.md`.
        max_bytes: Maximum raw byte count to inject before appending a truncation note.

    Returns:
        Full file content, capped content + truncation note, or "" if file is absent.
    """
    arch = data / store.ARCHITECTURE_NAME
    if not arch.exists():
        return ""
    raw = arch.read_bytes()
    if len(raw) <= max_bytes:
        return raw.decode("utf-8", errors="replace")
    truncated = raw[:max_bytes].decode("utf-8", errors="replace")
    return (
        truncated
        + f"\n\n[architecture.md truncated at {max_bytes} bytes — run /review-memory to trim]"
    )


def learnings_index(data: Path) -> str:
    """Return one index line per learning: relative path, summary, and read-when hint.

    Omits the body so building the index costs only N small header reads.
    Files without a `summary` frontmatter key are silently skipped.

    Args:
        data: Project data directory whose `learnings/` subdirectory is scanned.

    Returns:
        Newline-joined index lines, or "" when no summarized learnings exist.
    """
    learnings_dir = data / store.LEARNINGS_DIRNAME
    items = frontmatter.scan_learnings(learnings_dir)
    if not items:
        return ""
    lines: list[str] = []
    for path, summary, read_when in items:
        rel = path.relative_to(data)
        line = f"- {rel} — {summary}"
        if read_when:
            line += f"\n  read when: {'; '.join(read_when)}"
        lines.append(line)
    return "\n".join(lines)


def backlog_summary(data: Path) -> str:
    """Return a count-per-type summary plus open `[S]` (small) quick-win lines.

    Parses `## <type>` section headers and `- [ ]` open items. Surfaces only
    `[S]`-tagged items inline; larger items (M, L, XL) appear only in the totals
    so the injection stays concise.

    Args:
        data: Project data directory that may contain `backlog.md`.

    Returns:
        Summary string with total count, per-type counts, and one [S] line per quick-win,
        or "" when the file is absent or contains no open items.
    """
    backlog = data / store.BACKLOG_NAME
    if not backlog.exists():
        return ""
    text = backlog.read_text(encoding="utf-8")

    current_section: str | None = None
    counts: dict[str, int] = {}
    quick_wins: list[str] = []

    for line in text.splitlines():
        if line.startswith("## "):
            current_section = line[3:].strip()
        elif line.startswith("- [ ]") and current_section is not None:
            counts[current_section] = counts.get(current_section, 0) + 1
            if "[S]" in line:
                # Strip "- [ ] [S] " prefix and trailing date (" — YYYY-MM-DD")
                item_text = line[len("- [ ]") :].strip()
                item_text = item_text.replace("[S]", "", 1).strip()
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


def build_injection(data: Path, *, architecture_max_bytes: int) -> str:
    """Assemble the full XML-wrapped injection block, or "" when the store is empty.

    Collects architecture, learnings index, and backlog summary; returns "" when
    all three are empty (nothing to inject). Non-empty blocks are assembled under
    the fixed PREAMBLE and wrapped in `<recall-memory>…</recall-memory>`.

    Args:
        data: Project data directory to read from.
        architecture_max_bytes: Cap passed through to `architecture_block`.

    Returns:
        XML-wrapped injection string, or "" when the data directory is empty.
    """
    arch = architecture_block(data, max_bytes=architecture_max_bytes)
    index = learnings_index(data)
    backlog = backlog_summary(data)

    if not any([arch, index, backlog]):
        return ""

    parts: list[str] = [PREAMBLE]
    if arch:
        parts.append(f"## Architecture\n{arch}")
    if index:
        parts.append(f"## Learnings Index\n{index}")
    if backlog:
        parts.append(f"## Backlog\n{backlog}")

    content = "\n\n".join(parts)
    return f"<recall-memory>\n{content}\n</recall-memory>"
