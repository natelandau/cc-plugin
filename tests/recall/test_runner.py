"""Verify the headless claude runner seam (deterministic parts only; run() is never called)."""

from __future__ import annotations

import json

from recall.runner import (  # ty: ignore[unresolved-import]
    ClaudeRunner,
    RunResult,
    build_args,
    build_env,
    parse_stream_json,
)

# ---------------------------------------------------------------------------
# build_env (recursion guard + parent-process isolation)
# ---------------------------------------------------------------------------


def test_build_env_sets_headless_guard() -> None:
    """Verify build_env sets NL_RECALL_HEADLESS=1 in the returned dict."""
    # Given an empty base / When building the env
    result = build_env(base={})
    # Then the headless guard is set
    assert result["NL_RECALL_HEADLESS"] == "1"


def test_build_env_strips_parent_process_vars() -> None:
    """Verify build_env drops CLAUDECODE and CLAUDE_CODE_ENTRYPOINT but keeps the rest."""
    # Given a base carrying the parent Claude Code markers
    base = {"CLAUDECODE": "1", "CLAUDE_CODE_ENTRYPOINT": "cli", "HOME": "/home/user"}
    # When building the env
    result = build_env(base=base)
    # Then the markers are gone and unrelated keys survive
    assert "CLAUDECODE" not in result
    assert "CLAUDE_CODE_ENTRYPOINT" not in result
    assert result["HOME"] == "/home/user"


def test_build_env_does_not_mutate_base() -> None:
    """Verify build_env never modifies the caller's base mapping."""
    # Given a base dict with both vars present
    base = {"CLAUDECODE": "1", "X": "y"}
    original = dict(base)
    # When building the env
    build_env(base=base)
    # Then the base mapping is unchanged
    assert base == original


# ---------------------------------------------------------------------------
# build_args
# ---------------------------------------------------------------------------


def test_build_args_restricts_tools_and_persistence() -> None:
    """Verify build_args restricts tools, disables persistence, and skips permissions."""
    # Given a model / When building args
    args = build_args(model="claude-sonnet-4-6")
    # Then the safety-relevant flags are present
    assert args[args.index("--allowedTools") + 1] == "Read,Write,Edit"
    assert "--no-session-persistence" in args
    assert "--dangerously-skip-permissions" in args
    assert args[args.index("--output-format") + 1] == "stream-json"


def test_build_args_model_reflects_argument() -> None:
    """Verify the --model flag reflects the model argument."""
    # Given a custom model / When building args
    args = build_args(model="claude-opus-4-5")
    # Then the model flag matches
    assert args[args.index("--model") + 1] == "claude-opus-4-5"


def test_runner_uses_its_model() -> None:
    """Verify ClaudeRunner threads its configured model into the built args."""
    # Given a runner configured with a model
    args = ClaudeRunner(model="claude-test-model")._build_args()
    # Then its args carry that model
    assert args[args.index("--model") + 1] == "claude-test-model"


# ---------------------------------------------------------------------------
# parse_stream_json -> RunResult fields
# ---------------------------------------------------------------------------


def _stream(file_path: str) -> str:
    """Build sample stream-json reporting a Write to file_path plus a result line."""
    lines = [
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "tool_use", "name": "Write", "input": {"file_path": file_path}}
                    ]
                },
            }
        ),
        "",
        "not-json{{{",
        json.dumps({"type": "result", "result": "done"}),
    ]
    return "\n".join(lines)


def test_parse_stream_json_extracts_tool_and_result() -> None:
    """Verify parse_stream_json captures the written file and the final result text."""
    # Given sample stream-json output with one Write and a result
    tools, text = parse_stream_json(_stream("/home/u/out.md"))
    # Then the Write file and result text are recovered, junk lines skipped
    assert tools == [{"tool": "Write", "file": "/home/u/out.md"}]
    assert text == "done"


def test_parse_stream_json_path_fallback() -> None:
    """Verify parse_stream_json uses the 'path' input key when 'file_path' is absent."""
    # Given a tool_use block using 'path'
    line = json.dumps(
        {
            "type": "assistant",
            "message": {
                "content": [{"type": "tool_use", "name": "Read", "input": {"path": "/etc/hosts"}}]
            },
        }
    )
    # When parsing
    tools, _ = parse_stream_json(line)
    # Then the file key is set from 'path'
    assert tools[0]["file"] == "/etc/hosts"


def test_parse_stream_json_skips_junk() -> None:
    """Verify parse_stream_json returns empties on all-junk input without raising."""
    # Given only blank and malformed lines
    tools, text = parse_stream_json("\n\nnot-json{{{\n")
    # Then both outputs are empty
    assert tools == []
    assert text == ""


# ---------------------------------------------------------------------------
# RunResult is a structured value the sweep consumes
# ---------------------------------------------------------------------------


def test_run_result_holds_changed_files() -> None:
    """Verify RunResult exposes the structured fields Sweep reads."""
    # Given a constructed result
    result = RunResult(success=True, exit_code=0, changed_files=["a.md"], text="ok", stderr="")
    # Then its fields are accessible as a typed object
    assert result.changed_files == ["a.md"]
    assert result.success is True
