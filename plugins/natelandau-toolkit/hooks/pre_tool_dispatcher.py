#!/usr/bin/env -S uv run --script

# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///

"""Unified PreToolUse dispatcher.

Loads config once, routes to the checks applicable to the current
tool_name in safety-first order, and applies first-block-wins. Advisory
context from non-blocking checks is aggregated into one additionalContext
payload. Any exception inside a check is swallowed so a single broken
check never wedges tool execution.
"""

from __future__ import annotations

from lib.config import load_config
from lib.io import emit_block, emit_pre_advisory, read_payload
from lib.registry import applicable_checks


def main() -> None:
    """Entry point for the consolidated PreToolUse hook."""
    try:
        payload = read_payload()
        tool_name = payload.get("tool_name", "")
        cfg = load_config()
    except Exception as exc:  # noqa: BLE001 - resilience boundary: never wedge tools
        import sys

        print(f"natelandau-toolkit: dispatcher prelude failed: {exc}", file=sys.stderr)  # noqa: T201
        emit_pre_advisory([])  # NoReturn, exits 0

    contexts: list[str] = []
    for check in applicable_checks(tool_name, cfg):
        try:
            decision = check.evaluate(payload, cfg)
        except Exception as exc:  # noqa: BLE001 - resilience boundary: never wedge tools
            import sys

            print(f"natelandau-toolkit: check {check.id} errored: {exc}", file=sys.stderr)  # noqa: T201
            continue
        if decision is None:
            continue
        if decision.block:
            emit_block(decision.reason)  # exits 2
        if decision.context:
            contexts.append(decision.context)
    emit_pre_advisory(contexts)  # exits 0


if __name__ == "__main__":
    main()
