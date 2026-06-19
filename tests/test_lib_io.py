"""Unit tests for hooks/lib/io.py plus a subprocess import spike."""

from __future__ import annotations

import contextlib
import importlib.util
import io as _io
import json
import subprocess
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path
    from types import ModuleType


@contextlib.contextmanager
def pytest_raises_systemexit(code: int):
    """Assert the block raises SystemExit with the given code."""
    try:
        yield
    except SystemExit as exc:
        if exc.code != code:
            raise AssertionError(exc.code) from exc
        return
    msg = f"expected SystemExit({code})"
    raise AssertionError(msg)


def _load_io(hooks_dir: Path) -> ModuleType:
    """Import hooks/lib/io.py as a module for in-process unit tests."""
    spec = importlib.util.spec_from_file_location("_io_under_test", hooks_dir / "lib" / "io.py")
    assert spec
    assert spec.loader
    module = importlib.util.module_from_spec(spec)
    # Register before exec so dataclass string-annotation resolution finds the module in sys.modules.
    sys.modules["_io_under_test"] = module
    spec.loader.exec_module(module)
    return module


def test_decision_defaults(hooks_dir: Path) -> None:
    """Verify Decision has empty reason/context by default."""
    io = _load_io(hooks_dir)
    d = io.Decision(block=True)
    assert d.reason == ""
    assert d.context == ""


def test_emit_pre_advisory_silent_when_empty(hooks_dir: Path, capsys) -> None:
    """Verify emit_pre_advisory prints nothing and exits 0 with no contexts."""
    io = _load_io(hooks_dir)
    with pytest_raises_systemexit(0):
        io.emit_pre_advisory([])
    assert capsys.readouterr().out == ""


def test_emit_pre_advisory_joins_contexts(hooks_dir: Path, capsys) -> None:
    """Verify emit_pre_advisory emits joined additionalContext JSON, exit 0."""
    io = _load_io(hooks_dir)
    with pytest_raises_systemexit(0):
        io.emit_pre_advisory(["one", "two"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert payload["hookSpecificOutput"]["additionalContext"] == "one\ntwo"


def test_emit_block_writes_stderr_exit_2(hooks_dir: Path, capsys) -> None:
    """Verify emit_block writes the reason to stderr and exits 2."""
    io = _load_io(hooks_dir)
    with pytest_raises_systemexit(2):
        io.emit_block("BLOCKED: nope")
    assert "BLOCKED: nope" in capsys.readouterr().err


def test_read_payload_valid_object(hooks_dir: Path, monkeypatch) -> None:
    """Verify read_payload parses a well-formed JSON object from stdin."""
    # Given a valid JSON object on stdin
    io = _load_io(hooks_dir)
    monkeypatch.setattr(io.sys, "stdin", _io.StringIO('{"tool_name": "Bash"}'))

    # When reading the payload
    result = io.read_payload()

    # Then the parsed dict is returned
    assert result == {"tool_name": "Bash"}


def test_read_payload_malformed_returns_empty(hooks_dir: Path, monkeypatch) -> None:
    """Verify read_payload returns {} on truncated/invalid JSON instead of crashing."""
    # Given malformed JSON on stdin
    io = _load_io(hooks_dir)
    monkeypatch.setattr(io.sys, "stdin", _io.StringIO('{"tool_name": '))

    # When reading the payload
    result = io.read_payload()

    # Then it fails open to an empty dict
    assert result == {}


def test_read_payload_non_object_returns_empty(hooks_dir: Path, monkeypatch) -> None:
    """Verify read_payload rejects a valid-but-non-object JSON value."""
    # Given a JSON array (not an object) on stdin
    io = _load_io(hooks_dir)
    monkeypatch.setattr(io.sys, "stdin", _io.StringIO("[1, 2, 3]"))

    # When reading the payload
    result = io.read_payload()

    # Then it fails open to an empty dict
    assert result == {}


def test_read_payload_oversized_returns_empty(hooks_dir: Path, monkeypatch) -> None:
    """Verify read_payload rejects input past the cap even when it would parse."""
    # Given a tiny cap and an otherwise-valid object that exceeds it
    io = _load_io(hooks_dir)
    monkeypatch.setattr(io, "MAX_STDIN_BYTES", 10)
    monkeypatch.setattr(io.sys, "stdin", _io.StringIO('{"a": "bbbbbbbbbbbbbbbbb"}'))

    # When reading the payload
    result = io.read_payload()

    # Then the oversized stream is refused rather than partially parsed
    assert result == {}


def test_lib_import_spike(hooks_dir: Path) -> None:
    """Verify a uv run --script can import the sibling lib package (load-bearing)."""
    # Given a throwaway script that imports lib.io and prints a marker
    probe = hooks_dir / "_spike_probe.py"
    probe.write_text(
        "#!/usr/bin/env -S uv run --script\n"
        "# /// script\n# requires-python = '>=3.14'\n# dependencies = []\n# ///\n"
        "from lib.io import Decision\n"
        "print(Decision(block=False).block)\n",
        encoding="utf-8",
    )
    probe.chmod(probe.stat().st_mode | 0o111)  # make executable so the shebang fires
    try:
        # When running it through uv
        proc = subprocess.run([str(probe)], capture_output=True, text=True, timeout=60, check=False)
        # Then the sibling import resolves and the script runs
        assert proc.returncode == 0, proc.stderr
        assert "False" in proc.stdout
    finally:
        probe.unlink(missing_ok=True)
