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

import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

from lib import rules, transcript
from lib.config import load_config
from lib.io import read_payload
from lib.registry import hook_enabled

RULES_FILE = Path(__file__).parent / "stop_phrase_guard.rules.toml"
# Each [[violation]] needs a `reason` (shown to the assistant as the block
# correction); `id` is optional and unused in the output message.
STOP_REQUIRED = frozenset({"reason"})
STOP_OPTIONAL = frozenset({"id"})


def main() -> None:
    """Entry point for the Stop hook."""
    # Shared capped reader: bounds stdin and fails open to {} on malformed,
    # oversized, or non-object input (the guards below then no-op via .get()).
    data: dict[str, Any] = read_payload()

    # Already fired once this turn; let the assistant stop to avoid loops.
    if data.get("stop_hook_active"):
        sys.exit(0)

    transcript_path = data.get("transcript_path")
    if not transcript_path:
        sys.exit(0)

    cfg = load_config()
    if not hook_enabled("stop-phrase-guard", cfg):
        sys.exit(0)

    text = transcript.last_assistant_message_text(transcript.read_entries(transcript_path))
    if not text:
        sys.exit(0)

    # Load violations at invocation, not import, so a malformed TOML
    # surfaces a focused error message rather than a confusing import-time
    # traceback.
    try:
        violations = rules.load_rules(
            RULES_FILE, "violation", required=STOP_REQUIRED, optional=STOP_OPTIONAL
        )
    except (OSError, tomllib.TOMLDecodeError, TypeError, ValueError, re.error) as exc:
        print(  # noqa: T201
            f"stop_phrase_guard: failed to load {RULES_FILE.name}: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)

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
        sys.exit(0)

    decision = {
        "decision": "block",
        "reason": f"STOP HOOK VIOLATION: {violation.reason}",
    }
    print(json.dumps(decision))  # noqa: T201
    sys.exit(0)


if __name__ == "__main__":
    main()
