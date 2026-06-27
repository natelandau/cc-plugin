"""Shared module for `claude -p` subprocess invocations (the headless sweep seam).

Self-contained, stdlib only. Provides environment isolation (the recursion
guard), CLI argument construction, subprocess execution that never raises,
stream-json parsing, and prompt-template loading. Tests exercise only the
deterministic parts (build_env / build_args / parse_stream_json / load_template);
`run` is intentionally left untested to avoid spawning a real agent. The sweep
(lib/sweep.py) takes `run` as a default argument so its own tests can substitute
a fake.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

HEADLESS_ENV = "NL_RECALL_HEADLESS"
DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_TIMEOUT = 180


def build_env(*, base: Mapping[str, str]) -> dict[str, str]:
    """Build an isolated environment for the `claude -p` subprocess.

    Sets the headless guard so the spawned agent's own session hooks no-op, and
    drops CLAUDECODE / CLAUDE_CODE_ENTRYPOINT so the child is not treated as
    nested in the parent Claude Code process.

    Args:
        base: The base environment mapping to copy and modify.

    Returns:
        A new dict with the headless guard set and parent-process vars removed.
    """
    env = dict(base)
    env[HEADLESS_ENV] = "1"
    env.pop("CLAUDECODE", None)
    env.pop("CLAUDE_CODE_ENTRYPOINT", None)
    return env


def build_args(*, model: str = DEFAULT_MODEL) -> list[str]:
    """Construct the `claude -p` CLI argument list for a sweep run.

    Restricts the agent to file tools only (no Bash/network) and disables
    session persistence so the headless run leaves no transcript behind.

    Args:
        model: The Claude model ID to use for the headless run.

    Returns:
        Argument list ready to pass to subprocess.
    """
    return [
        "claude",
        "-p",
        "--model",
        model,
        "--output-format",
        "stream-json",
        "--verbose",
        "--allowedTools",
        "Read,Write,Edit",
        "--no-session-persistence",
        "--dangerously-skip-permissions",
    ]


def run(
    prompt: str,
    *,
    args: list[str],
    env: Mapping[str, str],
    cwd: str,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict[str, object]:
    """Execute `claude -p` and return a result dict, never raising.

    Returns keys: success (bool), exit_code (int), stdout (str), stderr (str).
    Failures map to negative exit codes: timeout -2, claude-not-found -3,
    OSError -5. The result dict is seeded with exit_code -1 as an unset sentinel
    that every code path overwrites, so -1 is never actually returned.

    Args:
        prompt: The prompt text to pass to the claude CLI via stdin.
        args: The CLI argument list (from build_args).
        env: The environment mapping for the subprocess.
        cwd: Working directory for the subprocess.
        timeout: Maximum seconds to wait for the subprocess.

    Returns:
        A dict with keys success, exit_code, stdout, and stderr.
    """
    result: dict[str, object] = {"success": False, "exit_code": -1, "stdout": "", "stderr": ""}
    try:
        proc = subprocess.run(  # noqa: S603 - args are caller-controlled (build_args)
            args,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            env=dict(env),
            check=False,
        )
    except subprocess.TimeoutExpired:
        result["exit_code"] = -2
        result["stderr"] = f"timed out after {timeout}s"
        return result
    except FileNotFoundError:
        result["exit_code"] = -3
        result["stderr"] = "claude CLI not found"
        return result
    except OSError as exc:
        result["exit_code"] = -5
        result["stderr"] = f"OSError: {exc}"
        return result
    result["exit_code"] = proc.returncode
    result["stdout"] = proc.stdout or ""
    result["stderr"] = proc.stderr or ""
    result["success"] = proc.returncode == 0
    return result


def _extract_tool_entries(content: list[object]) -> list[dict[str, str]]:
    """Extract tool_use blocks from a stream-json message content array.

    Args:
        content: The list of content blocks from an assistant message.

    Returns:
        A list of dicts with "tool" and optionally "file" keys for each tool_use block.
    """
    entries: list[dict[str, str]] = []
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        tool_entry: dict[str, str] = {"tool": str(block.get("name", "unknown"))}
        tool_input = block.get("input")
        if isinstance(tool_input, dict):
            file_path = tool_input.get("file_path") or tool_input.get("path") or ""
            if file_path:
                tool_entry["file"] = str(file_path)
        entries.append(tool_entry)
    return entries


def parse_stream_json(stdout: str) -> tuple[list[dict[str, str]], str]:
    """Parse stream-json output into (tools_used, result_text).

    tools_used collects one dict per assistant `tool_use` block ({"tool": name}
    plus "file" when the input carries a file_path/path). result_text is the
    final `result` entry's text. Malformed lines are skipped.

    Args:
        stdout: Raw stdout from the `claude -p --output-format stream-json` run.

    Returns:
        A tuple of (tools_used, result_text) where tools_used is a list of dicts
        with "tool" and optionally "file" keys, and result_text is the final result.
    """
    tools_used: list[dict[str, str]] = []
    result_text = ""
    for line in stdout.strip().split("\n"):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue
        message = entry.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, list):
            tools_used.extend(_extract_tool_entries(content))
        if entry.get("type") == "result":
            r = entry.get("result", "")
            if isinstance(r, str) and r:
                result_text = r
    return tools_used, result_text


def load_template(path: str | Path, **variables: str) -> str:
    """Read a template file and substitute {{name}} placeholders.

    Args:
        path: Path to the template file.
        **variables: Keyword arguments whose names map to {{name}} placeholders.

    Returns:
        The template content with all matching placeholders replaced.
    """
    content = Path(path).read_text(encoding="utf-8")
    for key, value in variables.items():
        content = content.replace("{{" + key + "}}", value)
    return content
