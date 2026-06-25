#!/usr/bin/env -S uv run --script

# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///

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

import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

from lib import rules, transcript
from lib.config import load_config
from lib.io import read_payload
from lib.profiles import hook_enabled

HOOK_ID = "capture-followups"
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


def main() -> None:
    """Entry point for the Stop hook."""
    # Shared capped reader: bounds stdin and fails open to {} on malformed,
    # oversized, or non-object input (the guards below then no-op via .get()).
    data: dict[str, Any] = read_payload()

    # Already fired once this turn; let the assistant stop to avoid loops. By
    # the time this re-fires the model has had its chance to record the item.
    if data.get("stop_hook_active"):
        sys.exit(0)

    transcript_path = data.get("transcript_path")
    if not transcript_path:
        sys.exit(0)

    cfg = load_config()
    if not hook_enabled(HOOK_ID, cfg):
        sys.exit(0)

    entries = transcript.read_entries(transcript_path)
    text = transcript.last_assistant_message_text(entries)
    if not text:
        sys.exit(0)

    # Load triggers at invocation, not import, so a malformed TOML surfaces a
    # focused error rather than a confusing import-time traceback.
    try:
        triggers = rules.load_rules(
            RULES_FILE, "trigger", required=TRIGGER_REQUIRED, optional=TRIGGER_OPTIONAL
        )
    except (OSError, tomllib.TOMLDecodeError, TypeError, ValueError, re.error) as exc:
        print(  # noqa: T201
            f"capture_followups: failed to load {RULES_FILE.name}: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Additive per-project triggers. Fail open inside load_project_rules so a
    # project typo never disables the built-in phrases.
    triggers = (
        *triggers,
        *rules.load_project_rules(
            RULES_FILE.name,
            "trigger",
            required=TRIGGER_REQUIRED,
            optional=TRIGGER_OPTIONAL,
            project_dir=cfg.project_dir,
        ),
    )

    # `text` is the primary match text; also expose it as `message` so a rule
    # may target it explicitly with `field = "message"`.
    trigger = rules.first_match(triggers, text=text, fields={"message": text})
    if trigger is None:
        sys.exit(0)

    # Already captured this turn (the model wrote the backlog inline, or this
    # is the continuation after an earlier block): nothing to enforce.
    backlog = cfg.option(HOOK_ID, "backlog", DEFAULT_BACKLOG)
    if transcript.file_written_since_last_user(
        entries, filename=Path(backlog).name, tool_names=WRITE_TOOLS
    ):
        sys.exit(0)

    decision = {
        "decision": "block",
        "reason": BLOCK_TEMPLATE.format(detail=trigger.reason, backlog=backlog),
    }
    print(json.dumps(decision))  # noqa: T201
    sys.exit(0)


if __name__ == "__main__":
    main()
