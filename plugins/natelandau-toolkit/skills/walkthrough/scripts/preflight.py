#!/usr/bin/env -S uv run --script

# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///

"""Check which capture tools and permissions are present before recording.

Usage: preflight.py PLATFORM [PLATFORM ...] [--screen] [--video] [--json]

PLATFORM is one of web, ios, macos, android. Each check runs once even when
several platforms need it. `--screen` makes Screen Recording a required macOS
check, for window stills taken with `screencapture -l`. `--video` implies it. Prints every check as `ok` or `MISSING` with the
install hint indented below, or a JSON list with `--json`. Exit codes: 0 when
every required check passes, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

PLATFORMS: tuple[str, ...] = ("web", "ios", "macos", "android")

_TIMEOUT = 20
_MIN_JAVA = 17
_SCREEN_PROBE = (
    'ObjC.import("CoreGraphics"); '
    'ObjC.bindFunction("CGPreflightScreenCaptureAccess", ["bool", []]); '
    "$.CGPreflightScreenCaptureAccess()"
)
_SCREEN_INSTALL = (
    "Grant Screen Recording to your terminal: "
    "System Settings > Privacy & Security > Screen Recording"
)


@dataclass(frozen=True)
class Check:
    """One tool or permission probe and what to run when it fails."""

    name: str
    ok: bool
    detail: str
    install: str | None = None
    required: bool = True


def parse_java_major(text: str) -> int | None:
    """Extract the major Java version from `java -version` output.

    Args:
        text: Combined stderr of `java -version`.

    Returns:
        The major version (`1.8` maps to 8), or None if no version is found.
    """
    match = re.search(r'version "(\d+)(?:\.(\d+))?', text)
    if match is None:
        return None
    major = int(match.group(1))
    if major == 1 and match.group(2) is not None:
        return int(match.group(2))
    return major


def has_ios_runtime(payload: dict[str, Any]) -> bool:
    """Report whether `xcrun simctl list runtimes --json` shows a usable iOS runtime.

    Args:
        payload: Parsed simctl JSON.

    Returns:
        True if any runtime named iOS is available.
    """
    runtimes = payload.get("runtimes")
    if not isinstance(runtimes, list):
        return False
    return any(
        isinstance(rt, dict)
        and str(rt.get("name", "")).startswith("iOS")
        and rt.get("isAvailable") is True
        for rt in runtimes
    )


def playwright_chromium_present(browsers_dir: Path) -> bool:
    """Report whether a Playwright browsers directory holds a Chromium build.

    Args:
        browsers_dir: Directory such as `~/Library/Caches/ms-playwright`.

    Returns:
        True if it contains any `chromium*` entry.
    """
    try:
        return any(browsers_dir.glob("chromium*"))
    except OSError:
        return False


def is_blank(gray: bytes, threshold: int = 8) -> bool:
    """Report whether a grayscale frame is uniformly dark.

    macOS returns an empty or black capture when Screen Recording is denied.

    Args:
        gray: Raw 8-bit grayscale pixels.
        threshold: Highest pixel value still counted as blank.

    Returns:
        True if the frame is empty or no pixel exceeds `threshold`.
    """
    return not gray or max(gray) <= threshold


def _run(args: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(args, capture_output=True, timeout=_TIMEOUT, check=False)  # noqa: S603


def _check(name: str, detail: str, install: str, *, ok: bool, required: bool = True) -> Check:
    return Check(name=name, ok=ok, detail=detail, install=install, required=required)


def _which(name: str, install: str, *, required: bool = True) -> Check:
    path = shutil.which(name)
    return _check(
        name, path or f"{name} not found on PATH", install, ok=path is not None, required=required
    )


def _check_java() -> Check:
    # The cask registers with /usr/libexec/java_home; the keg-only openjdk formula leaves java off PATH
    install = "brew install --cask temurin@21"
    if shutil.which("java") is None:
        return _check("java", "java not found on PATH", install, ok=False)
    try:
        proc = _run(["java", "-version"])
    except (OSError, subprocess.SubprocessError) as exc:
        return _check("java", f"java -version failed: {exc}", install, ok=False)
    major = parse_java_major(proc.stderr.decode(errors="replace"))
    if major is None:
        return _check("java", "could not parse java -version output", install, ok=False)
    return _check("java", f"Java {major} (need {_MIN_JAVA}+)", install, ok=major >= _MIN_JAVA)


def _check_chromium() -> Check:
    install = "shot-scraper install"
    env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    home = Path.home()
    candidates = (
        [Path(env)]
        if env
        else [home / "Library" / "Caches" / "ms-playwright", home / ".cache" / "ms-playwright"]
    )
    for directory in candidates:
        if playwright_chromium_present(directory):
            return _check("playwright-chromium", str(directory), install, ok=True)
    return _check("playwright-chromium", "no chromium* directory found", install, ok=False)


def _check_simctl() -> Check:
    install = "Install Xcode and an iOS simulator runtime (Xcode > Settings > Components)"
    if shutil.which("xcrun") is None:
        return _check("simctl", "xcrun not found on PATH", install, ok=False)
    try:
        proc = _run(["xcrun", "simctl", "list", "runtimes", "--json"])
        payload = json.loads(proc.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return _check("simctl", f"simctl failed: {exc}", install, ok=False)
    if proc.returncode != 0 or not isinstance(payload, dict):
        return _check("simctl", "simctl returned an error", install, ok=False)
    found = has_ios_runtime(payload)
    return _check(
        "simctl", "iOS runtime available" if found else "no iOS runtime", install, ok=found
    )


class _ProbeError(Exception):
    """The blank-frame probe could not produce a verdict."""


def _frame_is_blank() -> bool:
    """Capture the screen and report whether the frame came back blank.

    Only runs when the CoreGraphics probe fails. A denied capture on recent macOS
    can return a wallpaper-only frame, so this heuristic can pass falsely.

    Raises:
        _ProbeError: If ffmpeg fails or yields no pixels.
    """
    with tempfile.TemporaryDirectory() as tmp:
        shot = Path(tmp) / "probe.png"
        _run(["screencapture", "-x", str(shot)])
        if not shot.is_file() or shot.stat().st_size == 0:
            return True
        proc = _run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                str(shot),
                "-vf",
                "scale=32:32,format=gray",
                "-f",
                "rawvideo",
                "-",
            ]
        )
        if proc.returncode != 0 or not proc.stdout:
            msg = f"ffmpeg could not read the capture (exit {proc.returncode})"
            raise _ProbeError(msg)
        return is_blank(proc.stdout)


def _check_screen_recording() -> Check:
    try:
        proc = _run(["osascript", "-l", "JavaScript", "-e", _SCREEN_PROBE])
        answer = proc.stdout.decode(errors="replace").strip()
        if proc.returncode == 0 and answer in {"true", "false"}:
            granted = answer == "true"
            detail = "permission granted" if granted else "permission denied"
            return _check("screen-recording", detail, _SCREEN_INSTALL, ok=granted)
    except OSError, subprocess.SubprocessError:
        pass
    # The API probe is unavailable, so infer permission from a blank capture
    try:
        granted = not _frame_is_blank()
    except (OSError, subprocess.SubprocessError, _ProbeError) as exc:
        return _check("screen-recording", f"probe failed: {exc}", _SCREEN_INSTALL, ok=False)
    detail = "capture has content" if granted else "capture is blank, permission likely denied"
    return _check("screen-recording", detail, _SCREEN_INSTALL, ok=granted)


def run_checks(
    platforms: Sequence[str], *, video: bool = False, screen: bool = False
) -> list[Check]:
    """Probe the tools and permissions the given platforms need.

    Args:
        platforms: Any of `PLATFORMS`.
        video: Also require Screen Recording on macOS, for region video.
        screen: Also require Screen Recording on macOS, for window stills.

    Returns:
        One `Check` per distinct probe, in a stable order.
    """
    wanted = set(platforms)
    checks: list[Check] = [_which("ffmpeg", "brew install ffmpeg")]
    if "web" in wanted:
        checks.append(
            _which("shot-scraper", "uv tool install shot-scraper && shot-scraper install")
        )
        checks.append(_check_chromium())
    if wanted & {"ios", "android"}:
        checks.append(
            _which(
                "maestro", "brew tap mobile-dev-inc/tap && brew install mobile-dev-inc/tap/maestro"
            )
        )
        checks.append(_check_java())
    if "ios" in wanted:
        checks.append(_check_simctl())
    if "macos" in wanted:
        checks.append(_which("xcodebuild", "Install Xcode"))
        if video or screen:
            checks.append(_check_screen_recording())
        checks.append(_which("peekaboo", "brew install openclaw/tap/peekaboo", required=False))
    if "android" in wanted:
        checks.append(_which("adb", "brew install --cask android-platform-tools"))
    return checks


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Argument list; defaults to `sys.argv[1:]`.

    Returns:
        0 when every required check passes, 1 otherwise.
    """
    parser = argparse.ArgumentParser(description="Check capture tools for a walkthrough.")
    parser.add_argument("platforms", nargs="+", choices=PLATFORMS, metavar="PLATFORM")
    parser.add_argument("--screen", action="store_true")
    parser.add_argument("--video", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    checks = run_checks(args.platforms, video=args.video, screen=args.screen)
    if args.as_json:
        sys.stdout.write(json.dumps([asdict(c) for c in checks]) + "\n")
    else:
        for check in checks:
            status = "ok" if check.ok else "MISSING"
            optional = "" if check.required else " (optional)"
            sys.stdout.write(f"{status:8}{check.name}{optional}: {check.detail}\n")
            if not check.ok and check.install:
                sys.stdout.write(f"    {check.install}\n")
    return 0 if all(c.ok for c in checks if c.required) else 1


if __name__ == "__main__":
    raise SystemExit(main())
