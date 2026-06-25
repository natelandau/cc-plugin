#!/usr/bin/env -S uv run --script

# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///

"""Stop hook: catch ownership-dodging and permission-seeking phrases.

Reads the assistant's most recent message from the JSONL `transcript_path`
provided on the Stop hook's stdin, matches it against a list of phrase
patterns derived from CLAUDE.md golden rules, and on the first match
emits a `{decision: block, reason: ...}` JSON decision. Claude Code
reads the decision and forces the assistant to keep working with the
correction as its next instruction.

`last_assistant_message` does not exist on Stop hook input; the
assistant turn must be recovered by tailing `transcript_path`. Any
code reaching for `last_assistant_message` will silently see an empty
string and never fire. The transcript reading lives in
`lib/transcript.py` (Claude Code splits one message across per-block
JSONL lines, so the scan reconstructs the closing message by
`message.id`); this module only wires it to the rules engine.

Violation data lives in `stop_phrase_guard.rules.toml` next to this
file; the script loads it on every invocation. Edit that file to add,
remove, or tune a phrase.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Any

from lib import rules
from lib.io import Decision

if TYPE_CHECKING:
    from lib.config import Config

ID = "stop-phrase-guard"

RULES_FILE = Path(__file__).parent / "stop_phrase_guard.rules.toml"
# Each [[violation]] needs a `reason` (shown to the assistant as the block
# correction); `id` is optional and unused in the output message.
STOP_REQUIRED = frozenset({"reason"})
STOP_OPTIONAL = frozenset({"id"})


def evaluate(event: dict[str, Any], cfg: Config) -> Decision | None:
    """Block a Stop turn whose assistant message trips a phrase rule.

    The dispatcher pre-parses the transcript and exposes the closing
    assistant text as `event["assistant_message"]`; this check matches that
    text against the violation rules and returns a blocking Decision on the
    first hit, or None when the message is clean or empty.
    """
    text = event.get("assistant_message", "")
    if not text:
        return None

    # Load violations at invocation, not import, so a malformed TOML surfaces
    # a focused error message rather than a confusing import-time traceback.
    # The driver swallows the raise; built-in rules reload next invocation.
    try:
        violations = rules.load_rules(
            RULES_FILE, "violation", required=STOP_REQUIRED, optional=STOP_OPTIONAL
        )
    except (OSError, tomllib.TOMLDecodeError, TypeError, ValueError, re.error) as exc:
        print(  # noqa: T201
            f"stop_phrase_guard: failed to load {RULES_FILE.name}: {exc}",
            file=sys.stderr,
        )
        raise

    # Additive per-project violations. Fail open inside load_project_rules so a
    # project typo never disables the built-in phrases.
    violations = (
        *violations,
        *rules.load_project_rules(
            RULES_FILE.name,
            "violation",
            required=STOP_REQUIRED,
            optional=STOP_OPTIONAL,
            project_dir=cfg.project_dir,
        ),
    )

    # `text` is the primary match text; also expose it as the named field
    # `message` so a rule may target it explicitly with `field = "message"`.
    violation = rules.first_match(violations, text=text, fields={"message": text})
    if violation is None:
        return None
    return Decision(block=True, reason=f"STOP HOOK VIOLATION: {violation.reason}")
