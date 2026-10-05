"""Tests for the walkthrough skill's capture preflight (scripts/preflight.py)."""

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
def preflight():
    """Load preflight.py in-process."""
    return load_hook_module(SCRIPTS_DIR, "preflight.py", "wt_preflight")


def stub(
    bin_dir: Path,
    name: str,
    *,
    stdout: str = "",
    stderr: str = "",
    code: int = 0,
    body: str = "",
) -> None:
    """Write an executable shell stub named `name` into `bin_dir`."""
    lines = ["#!/bin/sh", body]
    if stdout:
        lines.append(f"printf %s {shlex.quote(stdout)}")
    if stderr:
        lines.append(f"printf %s {shlex.quote(stderr)} >&2")
    lines.append(f"exit {code}")
    path = bin_dir / name
    path.write_text("\n".join(lines) + "\n")
    path.chmod(0o755)


@pytest.fixture
def bin_dir(tmp_path, monkeypatch):
    """An empty directory that is the entire PATH, with HOME and browsers isolated."""
    bins = tmp_path / "bin"
    bins.mkdir()
    monkeypatch.setenv("PATH", str(bins))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path / "browsers"))
    return bins


def _by_name(checks: list) -> dict:
    return {c.name: c for c in checks}


def test_parse_java_major_handles_modern_and_legacy(preflight):
    # Given modern, legacy, and garbage `java -version` text
    # When the major version is parsed
    # Then each maps to the expected value
    assert preflight.parse_java_major('openjdk version "17.0.2" 2022-01-18') == 17
    assert preflight.parse_java_major('java version "1.8.0_292"') == 8
    assert preflight.parse_java_major("garbage") is None


def test_has_ios_runtime_requires_available_ios(preflight):
    # Given simctl runtime listings
    # When checked for a usable iOS runtime
    # Then only an available iOS runtime counts
    assert preflight.has_ios_runtime({"runtimes": [{"name": "iOS 26.0", "isAvailable": True}]})
    assert not preflight.has_ios_runtime({"runtimes": [{"name": "iOS 26.0", "isAvailable": False}]})
    assert not preflight.has_ios_runtime(
        {"runtimes": [{"name": "watchOS 12.0", "isAvailable": True}]}
    )
    assert not preflight.has_ios_runtime({})


def test_has_ios_runtime_tolerates_malformed_shapes(preflight):
    # Given payloads with unexpected shapes
    # When checked
    # Then none raises and all report False
    assert not preflight.has_ios_runtime({"runtimes": None})
    assert not preflight.has_ios_runtime({"runtimes": {"name": "iOS 26.0"}})
    assert not preflight.has_ios_runtime({"runtimes": ["iOS 26.0", 3, None]})


def test_playwright_chromium_present_matches_chromium_dirs(preflight, tmp_path):
    # Given a browsers dir with and without a chromium directory
    empty = tmp_path / "empty"
    empty.mkdir()
    full = tmp_path / "full"
    (full / "chromium-1234").mkdir(parents=True)

    # When probed
    # Then only the one with chromium* is present
    assert not preflight.playwright_chromium_present(empty)
    assert not preflight.playwright_chromium_present(tmp_path / "missing")
    assert preflight.playwright_chromium_present(full)


def test_is_blank_detects_uniform_frames(preflight):
    # Given an all-black frame and a frame with bright pixels
    # When checked
    # Then only the uniform frame is blank
    assert preflight.is_blank(bytes(1024))
    assert not preflight.is_blank(bytes(512) + bytes([200]) * 512)
    assert preflight.is_blank(b"")


def test_ffmpeg_checked_once_across_platforms(preflight, bin_dir):
    # Given no tools on PATH
    # When several platforms are checked
    names = [c.name for c in preflight.run_checks(["web", "ios", "macos"])]

    # Then ffmpeg appears once
    assert names.count("ffmpeg") == 1


def test_maestro_checked_once_for_ios_and_android(preflight, bin_dir):
    # Given no tools on PATH
    # When ios and android are checked together
    names = [c.name for c in preflight.run_checks(["ios", "android"])]

    # Then maestro and java appear once each
    assert names.count("maestro") == 1
    assert names.count("java") == 1


def test_missing_tool_reports_install_hint(preflight, bin_dir):
    # Given shot-scraper is not installed
    # When web is checked
    check = _by_name(preflight.run_checks(["web"]))["shot-scraper"]

    # Then the check fails with the verbatim install command
    assert not check.ok
    assert check.install == "uv tool install shot-scraper && shot-scraper install"


def test_web_chromium_found_via_browsers_path(preflight, bin_dir, tmp_path):
    # Given a chromium dir under PLAYWRIGHT_BROWSERS_PATH
    (tmp_path / "browsers" / "chromium-1").mkdir(parents=True)

    # When web is checked
    check = _by_name(preflight.run_checks(["web"]))["playwright-chromium"]

    # Then it is present
    assert check.ok


def test_web_chromium_missing_reports_install(preflight, bin_dir):
    # Given no chromium anywhere
    # When web is checked
    check = _by_name(preflight.run_checks(["web"]))["playwright-chromium"]

    # Then it fails with the install hint
    assert not check.ok
    assert check.install == "shot-scraper install"


def test_java_too_old_fails(preflight, bin_dir):
    # Given a Java 11 runtime
    stub(bin_dir, "java", stderr='openjdk version "11.0.2" 2019-01-15')

    # When android is checked
    check = _by_name(preflight.run_checks(["android"]))["java"]

    # Then it fails with the install hint
    assert not check.ok
    assert check.install == "brew install --cask temurin@21"


def test_java_17_passes(preflight, bin_dir):
    # Given a Java 17 runtime
    stub(bin_dir, "java", stderr='openjdk version "17.0.2" 2022-01-18')

    # When android is checked
    # Then java passes
    assert _by_name(preflight.run_checks(["android"]))["java"].ok


def test_simctl_ok_with_available_ios_runtime(preflight, bin_dir):
    # Given xcrun lists an available iOS runtime
    payload = json.dumps({"runtimes": [{"name": "iOS 26.0", "isAvailable": True}]})
    stub(bin_dir, "xcrun", stdout=payload)

    # When ios is checked
    # Then simctl passes
    assert _by_name(preflight.run_checks(["ios"]))["simctl"].ok


def test_simctl_fails_on_unparsable_output(preflight, bin_dir):
    # Given xcrun prints garbage
    stub(bin_dir, "xcrun", stdout="not json")

    # When ios is checked
    check = _by_name(preflight.run_checks(["ios"]))["simctl"]

    # Then it fails without raising
    assert not check.ok


def test_xcodebuild_checked_for_macos(preflight, bin_dir):
    # Given no xcodebuild
    # When macos is checked
    check = _by_name(preflight.run_checks(["macos"]))["xcodebuild"]

    # Then it fails with the install hint
    assert not check.ok
    assert check.install == "Install Xcode"


def test_adb_checked_for_android(preflight, bin_dir):
    # Given no adb
    # When android is checked
    check = _by_name(preflight.run_checks(["android"]))["adb"]

    # Then it fails with the install hint
    assert not check.ok
    assert check.install == "brew install --cask android-platform-tools"


def _screen_check_names(preflight, **flags) -> list[str]:
    return [c.name for c in preflight.run_checks(["macos"], **flags)]


def test_screen_recording_not_checked_without_screen_or_video(preflight, bin_dir):
    # Given macos without --screen or --video
    # When checked
    # Then no screen-recording check appears
    assert "screen-recording" not in _screen_check_names(preflight)


def test_screen_recording_required_with_screen_only(preflight, bin_dir):
    # Given the permission probe reports denied
    stub(bin_dir, "osascript", stdout="false")

    # When macos is checked with --screen and no --video
    check = _by_name(preflight.run_checks(["macos"], screen=True))["screen-recording"]
    code = preflight.main(["macos", "--screen"])

    # Then the check is present, required, and fails the exit code
    assert check.required
    assert not check.ok
    assert code == 1


def test_screen_recording_checked_with_video(preflight, bin_dir):
    # Given macos with --video only
    # When checked
    # Then the screen-recording check appears once
    assert _screen_check_names(preflight, video=True).count("screen-recording") == 1
    assert _screen_check_names(preflight, video=True, screen=True).count("screen-recording") == 1


def test_screen_recording_denied_is_required_failure(preflight, bin_dir):
    # Given the permission probe reports denied
    stub(bin_dir, "osascript", stdout="false")

    # When preflight runs for macos with video
    code = preflight.main(["macos", "--video"])

    # Then the check is required and failed, and main exits 1
    check = _by_name(preflight.run_checks(["macos"], video=True))["screen-recording"]
    assert not check.ok
    assert check.required
    assert code == 1
    assert "Screen Recording" in (check.install or "")


def test_screen_recording_granted_passes(preflight, bin_dir):
    # Given the permission probe reports granted
    stub(bin_dir, "osascript", stdout="true")

    # When macos is checked with video
    # Then screen-recording passes
    assert _by_name(preflight.run_checks(["macos"], video=True))["screen-recording"].ok


def _stub_fallback(bin_dir: Path, *, ffmpeg_body: str, ffmpeg_code: int = 0) -> None:
    stub(bin_dir, "osascript", code=1)
    stub(bin_dir, "screencapture", body='for a; do last="$a"; done; printf x > "$last"')
    stub(bin_dir, "ffmpeg", body=ffmpeg_body, code=ffmpeg_code)


def test_screen_recording_falls_back_to_blank_frame_probe(preflight, bin_dir):
    # Given the osascript probe fails and ffmpeg emits black pixels
    _stub_fallback(bin_dir, ffmpeg_body="/usr/bin/head -c 1024 /dev/zero")

    # When macos is checked with video
    check = _by_name(preflight.run_checks(["macos"], video=True))["screen-recording"]

    # Then the blank-frame path ran and treated the capture as denied
    assert not check.ok
    assert "blank" in check.detail


def test_screen_recording_fallback_passes_on_bright_frame(preflight, bin_dir):
    # Given the osascript probe fails and ffmpeg emits bright pixels
    _stub_fallback(bin_dir, ffmpeg_body="/usr/bin/head -c 1024 /dev/zero | /usr/bin/tr '\\0' 'x'")

    # When macos is checked with video
    check = _by_name(preflight.run_checks(["macos"], video=True))["screen-recording"]

    # Then the capture counts as granted
    assert check.ok
    assert "content" in check.detail


def test_screen_recording_fallback_reports_ffmpeg_failure(preflight, bin_dir):
    # Given the osascript probe fails and ffmpeg exits non-zero
    _stub_fallback(bin_dir, ffmpeg_body="", ffmpeg_code=1)

    # When macos is checked with video
    check = _by_name(preflight.run_checks(["macos"], video=True))["screen-recording"]

    # Then it reports a probe failure, not a blank frame
    assert not check.ok
    assert "blank" not in check.detail
    assert "ffmpeg" in check.detail


def test_peekaboo_missing_does_not_fail_exit(preflight, bin_dir):
    # Given every macos tool present except peekaboo
    stub(bin_dir, "ffmpeg")
    stub(bin_dir, "xcodebuild")

    # When main runs for macos
    code = preflight.main(["macos"])

    # Then it exits 0 and peekaboo is a non-required failure
    peekaboo = _by_name(preflight.run_checks(["macos"]))["peekaboo"]
    assert code == 0
    assert not peekaboo.ok
    assert not peekaboo.required


def test_main_human_output_lists_ok_and_missing_with_hint(preflight, bin_dir, capsys):
    # Given ffmpeg present and nothing else
    stub(bin_dir, "ffmpeg")

    # When main runs for web
    code = preflight.main(["web"])

    # Then output marks ok and MISSING and indents the install hint
    out = capsys.readouterr().out
    assert code == 1
    assert "ok" in out
    assert "MISSING" in out
    assert "    uv tool install shot-scraper && shot-scraper install" in out


def test_main_json_output_is_parseable(preflight, bin_dir, capsys):
    # Given nothing on PATH
    # When main runs with --json
    preflight.main(["web", "--json"])

    # Then stdout is a JSON list of checks
    data = json.loads(capsys.readouterr().out)
    assert {"name", "ok", "detail", "install", "required"} <= set(data[0])
    assert "ffmpeg" in [d["name"] for d in data]


def test_main_rejects_unknown_platform(preflight, bin_dir):
    # Given an unknown platform
    # When main parses it
    # Then argparse exits with status 2
    with pytest.raises(SystemExit) as exc:
        preflight.main(["windows"])
    assert exc.value.code == 2
