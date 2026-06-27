"""Verify the headless claude runner seam (pure parts only — run() is never called)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path
    from types import ModuleType


# ---------------------------------------------------------------------------
# build_env
# ---------------------------------------------------------------------------


def test_build_env_sets_headless_guard(load_recall_module: Callable[..., ModuleType]) -> None:
    """Verify build_env sets NL_RECALL_HEADLESS=1 in the returned dict."""
    # Given the claude_runner module
    runner = load_recall_module("lib", "claude_runner.py")

    # When building the env from an empty base
    result = runner.build_env(base={})

    # Then the headless guard is set
    assert result["NL_RECALL_HEADLESS"] == "1"


def test_build_env_removes_claudecode(load_recall_module: Callable[..., ModuleType]) -> None:
    """Verify build_env strips CLAUDECODE from the returned environment."""
    # Given the claude_runner module
    runner = load_recall_module("lib", "claude_runner.py")

    # When building the env from a base that contains CLAUDECODE
    base = {"CLAUDECODE": "1", "HOME": "/home/user"}
    result = runner.build_env(base=base)

    # Then CLAUDECODE is absent
    assert "CLAUDECODE" not in result
    # And unrelated keys are preserved
    assert result["HOME"] == "/home/user"


def test_build_env_removes_claude_code_entrypoint(
    load_recall_module: Callable[..., ModuleType],
) -> None:
    """Verify build_env strips CLAUDE_CODE_ENTRYPOINT from the returned environment."""
    # Given the claude_runner module
    runner = load_recall_module("lib", "claude_runner.py")

    # When building the env from a base that contains CLAUDE_CODE_ENTRYPOINT
    base = {"CLAUDE_CODE_ENTRYPOINT": "cli", "PATH": "/usr/bin"}
    result = runner.build_env(base=base)

    # Then CLAUDE_CODE_ENTRYPOINT is absent
    assert "CLAUDE_CODE_ENTRYPOINT" not in result


def test_build_env_does_not_mutate_base(load_recall_module: Callable[..., ModuleType]) -> None:
    """Verify build_env never modifies the caller's base mapping."""
    # Given the claude_runner module
    runner = load_recall_module("lib", "claude_runner.py")

    # Given a base dict with both vars present
    base = {"CLAUDECODE": "1", "CLAUDE_CODE_ENTRYPOINT": "cli", "X": "y"}
    original = dict(base)

    # When building the env
    runner.build_env(base=base)

    # Then the base mapping is unchanged
    assert base == original


# ---------------------------------------------------------------------------
# build_args
# ---------------------------------------------------------------------------


def test_build_args_includes_allowed_tools(load_recall_module: Callable[..., ModuleType]) -> None:
    """Verify build_args includes the Read,Write,Edit allowedTools flag."""
    # Given the claude_runner module
    runner = load_recall_module("lib", "claude_runner.py")

    # When building args with the default model
    args = runner.build_args()

    # Then the allowed tools flag is present
    assert "--allowedTools" in args
    idx = args.index("--allowedTools")
    assert args[idx + 1] == "Read,Write,Edit"


def test_build_args_includes_no_session_persistence(
    load_recall_module: Callable[..., ModuleType],
) -> None:
    """Verify build_args includes --no-session-persistence."""
    # Given the claude_runner module
    runner = load_recall_module("lib", "claude_runner.py")

    # When building args
    args = runner.build_args()

    # Then session persistence is disabled
    assert "--no-session-persistence" in args


def test_build_args_includes_dangerously_skip_permissions(
    load_recall_module: Callable[..., ModuleType],
) -> None:
    """Verify build_args includes --dangerously-skip-permissions."""
    # Given the claude_runner module
    runner = load_recall_module("lib", "claude_runner.py")

    # When building args
    args = runner.build_args()

    # Then permissions are skipped
    assert "--dangerously-skip-permissions" in args


def test_build_args_includes_stream_json_output_format(
    load_recall_module: Callable[..., ModuleType],
) -> None:
    """Verify build_args requests stream-json output format."""
    # Given the claude_runner module
    runner = load_recall_module("lib", "claude_runner.py")

    # When building args
    args = runner.build_args()

    # Then stream-json format is selected
    assert "--output-format" in args
    idx = args.index("--output-format")
    assert args[idx + 1] == "stream-json"


def test_build_args_model_reflects_argument(
    load_recall_module: Callable[..., ModuleType],
) -> None:
    """Verify the --model flag reflects the model= keyword argument."""
    # Given the claude_runner module
    runner = load_recall_module("lib", "claude_runner.py")

    # When building args with a custom model
    args = runner.build_args(model="claude-opus-4-5")

    # Then the model flag matches
    assert "--model" in args
    idx = args.index("--model")
    assert args[idx + 1] == "claude-opus-4-5"


def test_build_args_default_model(load_recall_module: Callable[..., ModuleType]) -> None:
    """Verify build_args uses the DEFAULT_MODEL when no model is specified."""
    # Given the claude_runner module
    runner = load_recall_module("lib", "claude_runner.py")

    # When building args without specifying a model
    args = runner.build_args()

    # Then the model flag is set to the default
    idx = args.index("--model")
    assert args[idx + 1] == runner.DEFAULT_MODEL


# ---------------------------------------------------------------------------
# parse_stream_json
# ---------------------------------------------------------------------------


_SAMPLE_FILE_PATH = "/home/user/notes/out.md"


def _make_stream_json_stdout() -> str:
    """Build a sample stream-json stdout string for parse_stream_json tests."""
    lines = [
        # A valid assistant message with a Write tool_use block that has a file_path
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Write",
                            "input": {"file_path": _SAMPLE_FILE_PATH, "content": "hello"},
                        }
                    ]
                },
            }
        ),
        # A blank line (should be skipped)
        "",
        # A malformed line (should be skipped)
        "not-json{{{",
        # A final result entry
        json.dumps({"type": "result", "result": "done"}),
    ]
    return "\n".join(lines)


def test_parse_stream_json_extracts_write_tool(
    load_recall_module: Callable[..., ModuleType],
) -> None:
    """Verify parse_stream_json returns the Write tool with its file path."""
    # Given the claude_runner module and sample stream-json output
    runner = load_recall_module("lib", "claude_runner.py")
    stdout = _make_stream_json_stdout()

    # When parsing the output
    tools_used, _ = runner.parse_stream_json(stdout)

    # Then the Write tool is captured with its file
    assert len(tools_used) == 1
    assert tools_used[0]["tool"] == "Write"
    assert tools_used[0]["file"] == _SAMPLE_FILE_PATH


def test_parse_stream_json_extracts_result_text(
    load_recall_module: Callable[..., ModuleType],
) -> None:
    """Verify parse_stream_json extracts the final result text."""
    # Given the claude_runner module and sample stream-json output
    runner = load_recall_module("lib", "claude_runner.py")
    stdout = _make_stream_json_stdout()

    # When parsing the output
    _tools, result_text = runner.parse_stream_json(stdout)

    # Then the result text is "done"
    assert result_text == "done"


def test_parse_stream_json_skips_junk_lines(
    load_recall_module: Callable[..., ModuleType],
) -> None:
    """Verify parse_stream_json ignores blank and malformed lines without raising."""
    # Given the claude_runner module and output with blank + malformed lines
    runner = load_recall_module("lib", "claude_runner.py")
    stdout = "\n\nnot-json{{{\n"

    # When parsing
    tools_used, result_text = runner.parse_stream_json(stdout)

    # Then both outputs are empty (nothing raised)
    assert tools_used == []
    assert result_text == ""


def test_parse_stream_json_path_fallback(
    load_recall_module: Callable[..., ModuleType],
) -> None:
    """Verify parse_stream_json uses 'path' key when 'file_path' is absent."""
    # Given the claude_runner module and a tool_use block that uses 'path' instead
    runner = load_recall_module("lib", "claude_runner.py")
    line = json.dumps(
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "name": "Read",
                        "input": {"path": "/etc/hosts"},
                    }
                ]
            },
        }
    )

    # When parsing
    tools_used, _ = runner.parse_stream_json(line)

    # Then the file key is set from the 'path' input
    assert tools_used[0]["file"] == "/etc/hosts"


# ---------------------------------------------------------------------------
# load_template
# ---------------------------------------------------------------------------


def test_load_template_substitutes_placeholders(
    tmp_path: Path, load_recall_module: Callable[..., ModuleType]
) -> None:
    """Verify load_template replaces {{transcript}} and {{x}} placeholders."""
    # Given the claude_runner module and a template file
    runner = load_recall_module("lib", "claude_runner.py")
    template = tmp_path / "prompt.md"
    template.write_text("Summary: {{transcript}}\nExtra: {{x}}\n", encoding="utf-8")

    # When loading with substitution vars
    result = runner.load_template(template, transcript="my notes", x="42")

    # Then both placeholders are replaced
    assert result == "Summary: my notes\nExtra: 42\n"


def test_load_template_leaves_absent_placeholder_untouched(
    tmp_path: Path, load_recall_module: Callable[..., ModuleType]
) -> None:
    """Verify load_template leaves placeholders that have no matching variable unchanged."""
    # Given the claude_runner module and a template with two placeholders
    runner = load_recall_module("lib", "claude_runner.py")
    template = tmp_path / "prompt.md"
    template.write_text("A: {{transcript}}\nB: {{missing}}\n", encoding="utf-8")

    # When loading with only one variable
    result = runner.load_template(template, transcript="data")

    # Then the unmatched placeholder is untouched
    assert "{{missing}}" in result
    assert "{{transcript}}" not in result


@pytest.mark.parametrize(
    ("template_text", "kwargs", "expected"),
    [
        ("hello {{name}}", {"name": "world"}, "hello world"),
        ("{{a}} and {{b}}", {"a": "X", "b": "Y"}, "X and Y"),
        ("no placeholders", {}, "no placeholders"),
    ],
)
def test_load_template_parametrized(
    tmp_path: Path,
    load_recall_module: Callable[..., ModuleType],
    template_text: str,
    kwargs: dict[str, str],
    expected: str,
) -> None:
    """Verify load_template substitution across multiple input shapes."""
    # Given the claude_runner module and a template
    runner = load_recall_module("lib", "claude_runner.py")
    template = tmp_path / "t.md"
    template.write_text(template_text, encoding="utf-8")

    # When loading with the given kwargs
    result = runner.load_template(template, **kwargs)

    # Then the result matches the expected string
    assert result == expected
