"""Stop hook: don't let deferred or recommended work vanish at end of turn.

Skills, slash commands, reviews, and the assistant's own analysis routinely
name work that is left undone: out-of-scope items, follow-up PRs, TODOs, a
refactor put off "for now". This hook detects that one situation - the
assistant is about to stop having named work it is not doing - and blocks the
Stop so the model deals with it deliberately.

It does NOT try to judge how big the work is; a regex cannot. The block message
routes instead: do the work now if it is small and in reach, or record it in
`.agent/BACKLOG.md` (with its rationale) if it is large, complex, risky, or
deserves its own plan. The agent makes that call. The turn passes if the model
already wrote the backlog this turn (self-suppression) or did the work.

Distinct from stop_phrase_guard, which is not a deferral hook: that one forces
the agent to stop dodging ("pre-existing", "not my change") and stop pausing
("should I continue", "pause here"). Trigger phrases here are kept clear of the
ones it owns, so the two hooks never issue contradictory corrections for the
same words.

Like stop_phrase_guard, the assistant turn is recovered from the JSONL
`transcript_path` (Stop input has no `last_assistant_message`); the shared
reader lives in `lib/transcript.py`. The same reader detects whether a
backlog write already happened this turn, which both prevents a false block
after the model complies and lets the model self-suppress by capturing the
item inline.

Trigger data lives in `capture_followups.rules.toml` next to this file and is
loaded on every invocation. A project may add triggers via
`<project>/.claude/natelandau-toolkit/capture_followups.rules.toml`.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from lib import rules, transcript
from lib.io import Decision

if TYPE_CHECKING:
    from lib.config import Config

ID = "capture-followups"
RULES_FILE = Path(__file__).parent / "capture_followups.rules.toml"
# Each [[trigger]] needs a `reason` (a short description of the deferral,
# spliced into the block message); `id` is optional and unused in the output.
TRIGGER_REQUIRED = frozenset({"reason"})
TRIGGER_OPTIONAL = frozenset({"id"})

# Where deferred work is recorded. Relative to the project root; overridable
# per project with [hooks.capture-followups].backlog in natelandau-toolkit.toml.
DEFAULT_BACKLOG = ".agent/BACKLOG.md"
# File-writing tools whose target is checked against the backlog file.
WRITE_TOOLS = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit"})

BLOCK_TEMPLATE = (
    "DEFERRED WORK: {detail} Decide which path this is, then act before you "
    "stop:\n"
    "  - If it is small and in reach, do NOT defer it - just do it now.\n"
    "  - If it is large, complex, risky, or deserves its own plan, spec, or "
    "decision, record it in {backlog} (create the file if it does not exist) so "
    "it is not lost:\n"
    "      - [ ] <imperative one-line description> - <today's date>\n"
    "        Source: <the skill, command, review, or analysis that raised it>\n"
    "        Why deferred: <too large | too complex | needs its own design/decision | carries risk>\n"
    "        Next step: <the concrete first action, e.g. write a spec or open an issue>\n"
    "Read the file first and skip the write if this item is already listed. "
    "Then you may stop."
)


def evaluate(event: dict[str, Any], cfg: Config) -> Decision | None:
    """Block a Stop turn that names deferred work without capturing it.

    The dispatcher pre-parses the transcript and exposes the closing
    assistant text as `event["assistant_message"]` and the turn's parsed
    entries as `event["entries"]`. This check matches the text against the
    trigger rules, then suppresses the block when the backlog file was
    written this turn (the model captured the item inline). Returns a
    blocking Decision, or None when clean, empty, or already captured.
    """
    text = event.get("assistant_message", "")
    if not text:
        return None
    entries = event.get("entries", [])

    # Built-in triggers raise on malformed TOML (the driver swallows it and
    # reloads next invocation); project triggers are additive and fail open.
    triggers = rules.load_all_rules(
        RULES_FILE,
        "trigger",
        required=TRIGGER_REQUIRED,
        optional=TRIGGER_OPTIONAL,
        project_dir=cfg.project_dir,
        label="capture_followups",
    )

    # `text` is the primary match text; also expose it as `message` so a rule
    # may target it explicitly with `field = "message"`.
    trigger = rules.first_match(triggers, text=text, fields={"message": text})
    if trigger is None:
        return None

    # Already captured this turn (the model wrote the backlog inline, or this
    # is the continuation after an earlier block): nothing to enforce.
    backlog = cfg.option(ID, "backlog", DEFAULT_BACKLOG)
    if transcript.file_written_since_last_user(
        entries, filename=Path(backlog).name, tool_names=WRITE_TOOLS
    ):
        return None
    return Decision(
        block=True, reason=BLOCK_TEMPLATE.format(detail=trigger.reason, backlog=backlog)
    )
