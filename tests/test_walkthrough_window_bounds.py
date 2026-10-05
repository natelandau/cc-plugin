"""Tests for the walkthrough skill's window locator (scripts/window_bounds.py)."""

from __future__ import annotations

import json
import shlex
from pathlib import Path

import pytest

from tests._helpers import load_hook_module

SCRIPTS_DIR = (
    Path(__file__).resolve().parent.parent
    / "plugins"
    / "natelandau-toolkit"
    / "skills"
    / "walkthrough"
    / "scripts"
)


@pytest.fixture
def wb():
    """Load window_bounds.py in-process."""
    return load_hook_module(SCRIPTS_DIR, "window_bounds.py", "wt_window_bounds")


def _stub_osascript(bin_dir: Path, stdout: str, code: int = 0) -> None:
    path = bin_dir / "osascript"
    path.write_text(f"#!/bin/sh\nprintf %s {shlex.quote(stdout)}\nexit {code}\n")
    path.chmod(0o755)


@pytest.fixture
def bin_dir(tmp_path, monkeypatch):
    """An empty directory that is the entire PATH."""
    bins = tmp_path / "bin"
    bins.mkdir()
    monkeypatch.setenv("PATH", str(bins))
    return bins


def _raw(*rows: dict) -> str:
    return json.dumps(list(rows))


def _row(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": 1,
        "owner": "ExampleApp",
        "title": "",
        "x": 0,
        "y": 0,
        "w": 800,
        "h": 600,
        "alpha": 1,
    }
    return base | overrides


def test_pick_window_prefers_largest_case_insensitive(wb):
    # Given two windows of one app, the second larger
    ws = [
        wb.Window(1, "ExampleApp", "", 0, 0, 100, 100),
        wb.Window(2, "ExampleApp", "", 0, 0, 800, 600),
    ]
    # When picking with a differently-cased app name
    # Then the larger window wins
    assert wb.pick_window(ws, "exampleapp").id == 2


def test_pick_window_filters_by_title(wb):
    # Given two windows with different titles, the untitled-match one smaller
    ws = [
        wb.Window(1, "App", "Settings", 0, 0, 300, 300),
        wb.Window(2, "App", "Main", 0, 0, 900, 900),
    ]
    # When picking with a title substring
    # Then only the matching window is eligible, case-insensitively
    assert wb.pick_window(ws, "App", title="sett").id == 1


def test_pick_window_none_when_absent(wb):
    # Given windows of another app
    ws = [wb.Window(1, "Other", "", 0, 0, 800, 600)]
    # When picking an absent app or title
    # Then nothing is returned
    assert wb.pick_window(ws, "ExampleApp") is None
    assert wb.pick_window([wb.Window(1, "App", "A", 0, 0, 800, 600)], "App", title="zzz") is None


@pytest.mark.parametrize("size", [(1, 1), (50, 50), (99, 800), (800, 99)])
def test_pick_window_never_picks_helper_sized_window(wb, size):
    # Given a tiny helper window as the only match
    ws = [wb.Window(1, "App", "", 0, 0, *size)]
    # When picking
    # Then it is never chosen
    assert wb.pick_window(ws, "App") is None


def test_pick_window_does_not_require_a_title(wb):
    # Given a large window with an empty title (no Screen Recording permission)
    ws = [wb.Window(7, "App", "", 0, 0, 400, 300)]
    # When picking without a title filter
    # Then it is found
    assert wb.pick_window(ws, "App").id == 7


def test_parse_windows_round_trip(wb):
    # Given JXA output with a visible window
    raw = _raw(_row(id=5, owner="Finder", title="Docs", x=10, y=20, w=300, h=200))
    # When parsing
    # Then every field is carried over
    assert wb.parse_windows(raw) == [wb.Window(5, "Finder", "Docs", 10, 20, 300, 200)]


def test_parse_windows_drops_transparent_windows(wb):
    # Given a fully transparent window and an opaque one
    raw = _raw(_row(id=1, alpha=0), _row(id=2, alpha=1))
    # When parsing
    # Then the transparent one is dropped
    assert [w.id for w in wb.parse_windows(raw)] == [2]


@pytest.mark.parametrize("raw", ["", "not json", "{}", '[{"id": 1}]', '["x"]'])
def test_parse_windows_tolerates_garbage(wb, raw):
    # Given unusable osascript output
    # When parsing
    # Then no windows come back and nothing raises
    assert wb.parse_windows(raw) == []


def test_jxa_uses_numeric_options_and_binds_function(wb):
    # Given the bundled program
    # Then it binds the CoreGraphics call and filters on layer and alpha
    assert "bindFunction" in wb.JXA
    assert "CGWindowListCopyWindowInfo" in wb.JXA
    assert "kCGWindowLayer" in wb.JXA
    assert "kCGWindowAlpha" in wb.JXA


def test_main_prints_screencapture_rect(wb, bin_dir, capsys):
    # Given osascript stubbed to print one window at 10,20 sized 300x200
    _stub_osascript(bin_dir, _raw(_row(owner="Finder", x=10, y=20, w=300, h=200)))
    # When running the CLI
    code = wb.main(["finder"])
    # Then stdout is the screencapture -R argument
    assert code == 0
    assert capsys.readouterr().out.strip() == "10,20,300,200"


def test_main_json_includes_id(wb, bin_dir, capsys):
    # Given a stubbed window
    _stub_osascript(bin_dir, _raw(_row(id=42, owner="Finder", x=1, y=2, w=300, h=200)))
    # When running with --json
    code = wb.main(["Finder", "--json"])
    # Then the full window is printed
    assert code == 0
    assert json.loads(capsys.readouterr().out)["id"] == 42


def test_main_exit_1_lists_owners_seen(wb, bin_dir, capsys):
    # Given only other apps are open
    _stub_osascript(bin_dir, _raw(_row(owner="Mail"), _row(id=2, owner="Notes")))
    # When asking for an absent app
    code = wb.main(["ExampleApp"])
    # Then exit 1 and stderr names the owners seen
    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert "Mail" in captured.err
    assert "Notes" in captured.err


def test_main_exit_1_when_osascript_fails(wb, bin_dir, capsys):
    # Given osascript exits non-zero
    _stub_osascript(bin_dir, "", code=1)
    # When running the CLI
    # Then it exits 1 rather than raising
    assert wb.main(["Finder"]) == 1
    assert capsys.readouterr().err


def test_parse_windows_tolerates_infinite_values(wb):
    # Given a row whose coordinate is infinite (int() raises OverflowError)
    raw = '[{"id": 1, "owner": "A", "title": "", "x": 1e999, "y": 0, "w": 300, "h": 300}]'
    # When parsing
    # Then the row is dropped and nothing raises
    assert wb.parse_windows(raw) == []


def test_main_hints_at_permission_when_titles_all_empty(wb, bin_dir, capsys):
    # Given windows whose titles are all empty and a --title filter
    _stub_osascript(bin_dir, _raw(_row(owner="App", title="")))
    # When the title filter matches nothing
    code = wb.main(["App", "--title", "Main"])
    # Then stderr points at Screen Recording permission
    assert code == 1
    assert "Screen Recording" in capsys.readouterr().err


def test_main_no_permission_hint_without_title_filter(wb, bin_dir, capsys):
    # Given an absent app and no --title
    _stub_osascript(bin_dir, _raw(_row(owner="Mail", title="")))
    # When running
    wb.main(["App"])
    # Then no permission hint is printed
    assert "Screen Recording" not in capsys.readouterr().err


def test_main_exit_1_when_osascript_times_out(wb, monkeypatch, capsys):
    # Given the osascript call times out
    def boom(*_a: object, **_k: object) -> None:
        cmd = "osascript"
        raise wb.subprocess.TimeoutExpired(cmd, 1)

    monkeypatch.setattr(wb.subprocess, "run", boom)
    # When running the CLI
    # Then it exits 1 with a message and no traceback
    assert wb.main(["Finder"]) == 1
    assert "osascript failed" in capsys.readouterr().err


def test_main_exit_1_when_osascript_missing(wb, bin_dir, capsys):
    # Given an empty PATH with no osascript
    assert not list(bin_dir.iterdir())
    # When running the CLI
    # Then it exits 1 with a message and no traceback
    assert wb.main(["Finder"]) == 1
    assert "osascript failed" in capsys.readouterr().err


def test_jxa_lists_all_windows_not_only_on_screen(wb):
    # Given the bundled program
    # Then it passes option value 16 and not the on-screen-only constant
    assert "const options = 16;" in wb.JXA
    assert "onScreenOnly" not in wb.JXA
    assert "kCGWindowIsOnscreen" in wb.JXA


def test_parse_windows_reads_on_screen(wb):
    # Given one on-screen row, one off-screen row, one row without the key
    raw = _raw(
        _row(id=1, on_screen=True),
        _row(id=2, on_screen=False),
        _row(id=3),
    )
    # When parsing
    # Then missing on_screen defaults to False
    assert [w.on_screen for w in wb.parse_windows(raw)] == [True, False, False]


def test_pick_window_prefers_on_screen_over_larger_off_screen(wb):
    # Given a small on-screen window and a larger off-screen one
    ws = [
        wb.Window(1, "App", "", 0, 0, 900, 900, on_screen=False),
        wb.Window(2, "App", "", 0, 0, 300, 300, on_screen=True),
    ]
    # When picking
    # Then the on-screen window wins
    assert wb.pick_window(ws, "App").id == 2


def test_pick_window_returns_off_screen_when_only_match(wb):
    # Given only an off-screen window (Stage Manager or another Space)
    ws = [wb.Window(1, "App", "", 0, 0, 800, 600, on_screen=False)]
    # When picking
    # Then it is still returned
    assert wb.pick_window(ws, "App").id == 1


def test_main_json_includes_on_screen(wb, bin_dir, capsys):
    # Given a stubbed on-screen window
    _stub_osascript(bin_dir, _raw(_row(owner="Finder", on_screen=True)))
    # When running with --json
    wb.main(["Finder", "--json"])
    # Then on_screen is reported
    assert json.loads(capsys.readouterr().out)["on_screen"] is True


def test_jxa_reports_owner_pid_and_coerces_on_screen(wb):
    # Given the bundled program
    # Then it reports the owner PID and coerces the on-screen flag to a boolean
    assert "kCGWindowOwnerPID" in wb.JXA
    assert "!!win.kCGWindowIsOnscreen" in wb.JXA


def test_parse_windows_reads_pid(wb):
    # Given one row with an owner PID and one without
    raw = _raw(_row(id=1, pid=4242), _row(id=2))
    # When parsing
    # Then the PID is carried over, and a missing PID is None
    assert [w.pid for w in wb.parse_windows(raw)] == [4242, None]


def test_pick_window_filters_by_pid(wb):
    # Given the user's visible copy and the run's off-screen copy, same owner name
    ws = [
        wb.Window(1, "ExampleApp", "", 0, 0, 900, 900, on_screen=True, pid=100),
        wb.Window(2, "ExampleApp", "", 0, 0, 800, 600, on_screen=False, pid=200),
    ]
    # When picking with the PID of the run's copy
    # Then only that copy's window is eligible
    assert wb.pick_window(ws, "ExampleApp", pid=200).id == 2
    assert wb.pick_window(ws, "ExampleApp", pid=300) is None


def test_main_pid_flag_selects_that_process(wb, bin_dir, capsys):
    # Given two windows with the same owner name in different processes
    _stub_osascript(
        bin_dir,
        _raw(
            _row(id=1, pid=100, on_screen=True, w=900, h=900),
            _row(id=2, pid=200, on_screen=True),
        ),
    )
    # When running with --pid
    code = wb.main(["ExampleApp", "--pid", "200", "--json"])
    # Then the window of that process is printed, with its pid
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert out["id"] == 2
    assert out["pid"] == 200


def test_main_on_screen_flag_rejects_off_screen_window(wb, bin_dir, capsys):
    # Given the app's only window is off screen
    _stub_osascript(bin_dir, _raw(_row(on_screen=False)))
    # When asking for bounds that must be on screen
    code = wb.main(["ExampleApp", "--on-screen"])
    # Then exit 1, no bounds on stdout, and stderr says why
    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert "off screen" in captured.err


def test_main_on_screen_flag_passes_on_screen_window(wb, bin_dir, capsys):
    # Given the app's window is on screen
    _stub_osascript(bin_dir, _raw(_row(on_screen=True, x=5, y=6, w=300, h=200)))
    # When asking for bounds that must be on screen
    code = wb.main(["ExampleApp", "--on-screen"])
    # Then the bounds are printed
    assert code == 0
    assert capsys.readouterr().out.strip() == "5,6,300,200"
