#!/usr/bin/env -S uv run --script

# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///

"""Find a macOS app window's rectangle and id for `screencapture`.

Usage: window_bounds.py APP [--title T] [--pid PID] [--on-screen] [--json]

Prints `x,y,w,h`, the argument for `screencapture -R`. With `--json`, prints
the whole window including `id`, the argument for `screencapture -l`. Exit
codes: 0 when a window matches, 1 otherwise (stderr lists the app names seen).

Only windows at layer 0 that are at least 100x100 are considered, so blank
helper windows are never picked. Windows that are off screen (hidden by Stage
Manager, or on another Space) are included because `screencapture -l` captures
them at full resolution. `on_screen` tells callers whether clicking or region
capture is possible without bringing the app forward; an on-screen window
is preferred over an off-screen one. `--on-screen` exits 1 when the picked
window is off screen, because `screencapture -R` would then record whatever
the user has at those coordinates. `--pid` limits the match to one process,
so another copy of the app with the same owner name never wins. Window titles are empty without Screen
Recording permission, so `--title` needs it; bounds and owner do not. Values
are points, which is what `screencapture -R` takes, so no retina scaling is
applied. The program only lists windows. It never moves, focuses, or captures anything.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass

_TIMEOUT = 20
_MIN_SIDE = 100

# Numeric option values and an explicit bind because JXA does not bridge the
# CoreGraphics constants or the function signature by itself.
JXA = """
ObjC.import("CoreGraphics");
ObjC.bindFunction("CGWindowListCopyWindowInfo", ["id", ["unsigned int", "unsigned int"]]);
const options = 16;
const list = ObjC.deepUnwrap($.CGWindowListCopyWindowInfo(options, 0)) || [];
const out = [];
for (const win of list) {
  if (win.kCGWindowLayer !== 0) continue;
  const b = win.kCGWindowBounds || {};
  out.push({
    id: win.kCGWindowNumber,
    owner: win.kCGWindowOwnerName || "",
    pid: win.kCGWindowOwnerPID,
    title: win.kCGWindowName || "",
    alpha: win.kCGWindowAlpha === undefined ? 1 : win.kCGWindowAlpha,
    on_screen: !!win.kCGWindowIsOnscreen,
    x: Math.round(b.X), y: Math.round(b.Y),
    w: Math.round(b.Width), h: Math.round(b.Height),
  });
}
JSON.stringify(out);
"""


@dataclass(frozen=True)
class Window:
    """One window as reported by CoreGraphics."""

    id: int
    owner: str
    title: str
    x: int
    y: int
    w: int
    h: int
    on_screen: bool = False
    pid: int | None = None


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    try:
        return int(value)
    except OverflowError, ValueError:
        return None


def _to_window(row: object) -> Window | None:
    if not isinstance(row, dict):
        return None
    try:
        if float(row.get("alpha", 1)) <= 0:
            return None
        return Window(
            id=int(row["id"]),
            owner=str(row["owner"]),
            title=str(row.get("title", "")),
            x=int(row["x"]),
            y=int(row["y"]),
            w=int(row["w"]),
            h=int(row["h"]),
            on_screen=row.get("on_screen") is True,
            pid=_optional_int(row.get("pid")),
        )
    except KeyError, TypeError, ValueError, OverflowError:
        return None


def parse_windows(raw: str) -> list[Window]:
    """Parse the JXA program's JSON output, dropping transparent windows.

    Args:
        raw: Stdout of the `JXA` program.

    Returns:
        The windows; an empty list if `raw` is not a JSON list.
    """
    try:
        rows = json.loads(raw)
    except ValueError:
        return []
    if not isinstance(rows, list):
        return []
    return [w for w in map(_to_window, rows) if w is not None]


def pick_window(
    windows: list[Window], app: str, title: str | None = None, pid: int | None = None
) -> Window | None:
    """Choose the main window of an app.

    Helper windows under 100 points on a side are skipped so a blank
    auxiliary window never wins over the real one.

    Args:
        windows: Candidates from `parse_windows`.
        app: Owner name, matched case-insensitively.
        title: Optional case-insensitive title substring.
        pid: Optional owner process id; other processes are ignored.

    Returns:
        The largest matching window, preferring on-screen ones, or None.
    """
    wanted = app.casefold()
    needle = title.casefold() if title is not None else None
    matches = [
        w
        for w in windows
        if w.w >= _MIN_SIDE
        and w.h >= _MIN_SIDE
        and w.owner.casefold() == wanted
        and (needle is None or needle in w.title.casefold())
        and (pid is None or w.pid == pid)
    ]
    if not matches:
        return None
    return max(matches, key=lambda w: (w.on_screen, w.w * w.h))


def list_windows() -> list[Window]:
    """Run the JXA program and parse its output.

    Returns:
        The windows.

    Raises:
        RuntimeError: If osascript cannot run or exits non-zero.
    """
    try:
        proc = subprocess.run(  # noqa: S603
            ["osascript", "-l", "JavaScript", "-e", JXA],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        msg = f"osascript failed: {exc}"
        raise RuntimeError(msg) from exc
    if proc.returncode != 0:
        msg = f"osascript exited {proc.returncode}: {proc.stderr.strip()}"
        raise RuntimeError(msg)
    return parse_windows(proc.stdout)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Argument list; defaults to `sys.argv[1:]`.

    Returns:
        0 when a window matches, 1 otherwise.
    """
    parser = argparse.ArgumentParser(description="Locate a macOS app window for capture.")
    parser.add_argument("app")
    parser.add_argument("--title")
    parser.add_argument("--pid", type=int)
    parser.add_argument("--on-screen", action="store_true", dest="on_screen")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    try:
        windows = list_windows()
    except RuntimeError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    found = pick_window(windows, args.app, args.title, args.pid)
    if found is None:
        owners = ", ".join(sorted({w.owner for w in windows})) or "none"
        sys.stderr.write(f"No window found for {args.app!r}. Apps seen: {owners}\n")
        if args.title is not None and not any(w.title for w in windows):
            sys.stderr.write("Window titles are empty: they need Screen Recording permission.\n")
        return 1
    if args.on_screen and not found.on_screen:
        sys.stderr.write(
            f"Window {found.id} of {args.app!r} is off screen. "
            "Bring the app to the front, then run again.\n"
        )
        return 1
    if args.as_json:
        sys.stdout.write(json.dumps(asdict(found)) + "\n")
    else:
        sys.stdout.write(f"{found.x},{found.y},{found.w},{found.h}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
