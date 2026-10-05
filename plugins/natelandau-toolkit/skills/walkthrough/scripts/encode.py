#!/usr/bin/env -S uv run --script

# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///

"""Encode a screen recording into a small web-safe MP4 plus a poster PNG.

Usage: encode.py SRC --out-dir DIR [--max-width N] [--start S] [--end E]

Prints `{"mp4": "...", "poster": "..."}` on success. Exit codes: 0 ok,
1 ffmpeg failed (last 20 stderr lines on stderr), 2 ffmpeg not installed.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

_BASE = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
_STDERR_TAIL_LINES = 20


class EncodeError(Exception):
    """ffmpeg exited non-zero; carries the tail of its stderr."""


def mp4_args(
    src: Path,
    dst: Path,
    *,
    max_width: int = 1280,
    start: float | None = None,
    end: float | None = None,
) -> list[str]:
    """Build the ffmpeg argv that encodes `src` to a silent, fast-start H.264 MP4.

    Args:
        src: Input recording in any format ffmpeg reads.
        dst: Output MP4 path.
        max_width: Downscale wider videos to this width; never upscale.
        start: Optional trim start in seconds.
        end: Optional trim end in seconds.

    Returns:
        The full argv, starting with `ffmpeg`.
    """
    args = list(_BASE)
    if start is not None:
        args += ["-ss", str(start)]
    if end is not None:
        args += ["-to", str(end)]
    args += [
        "-i",
        str(src),
        # -2 keeps the height even, which yuv420p requires
        "-vf",
        f"scale='min(iw,{max_width})':-2",
        "-c:v",
        "libx264",
        "-crf",
        "28",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-an",
        str(dst),
    ]
    return args


def poster_args(mp4: Path, dst: Path, *, from_end: bool = True) -> list[str]:
    """Build the ffmpeg argv that saves the final frame of `mp4` as a PNG.

    Args:
        mp4: Encoded MP4 to read.
        dst: Output PNG path.
        from_end: Seek to just before the end; otherwise take the first frame.

    Returns:
        The full argv, starting with `ffmpeg`.
    """
    seek = ["-sseof", "-0.1"] if from_end else []
    return [
        *_BASE,
        *seek,
        "-i",
        str(mp4),
        "-frames:v",
        "1",
        "-update",
        "1",
        str(dst),
    ]


def _run(args: list[str]) -> None:
    """Run ffmpeg, raising EncodeError with the stderr tail on failure."""
    proc = subprocess.run(args, capture_output=True, text=True, check=False)  # noqa: S603
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.splitlines()[-_STDERR_TAIL_LINES:])
        raise EncodeError(tail)


def encode(
    src: Path,
    out_dir: Path,
    *,
    max_width: int = 1280,
    start: float | None = None,
    end: float | None = None,
) -> tuple[Path, Path]:
    """Encode `src` into `out_dir` and extract its poster.

    Args:
        src: Input recording.
        out_dir: Directory for the outputs; created if missing.
        max_width: Downscale wider videos to this width.
        start: Optional trim start in seconds.
        end: Optional trim end in seconds.

    Returns:
        `(out_dir/<stem>.mp4, out_dir/<stem>.poster.png)`.

    Raises:
        ValueError: If the MP4 output path is the source file itself.
        EncodeError: If ffmpeg fails.
    """
    mp4 = out_dir / f"{src.stem}.mp4"
    poster = out_dir / f"{src.stem}.poster.png"
    if mp4.resolve() == src.resolve():
        msg = f"output {mp4} would overwrite the source; use a different --out-dir"
        raise ValueError(msg)

    out_dir.mkdir(parents=True, exist_ok=True)
    _run(mp4_args(src, mp4, max_width=max_width, start=start, end=end))

    try:
        _run(poster_args(mp4, poster))
    except EncodeError:
        poster.unlink(missing_ok=True)
    if not poster.exists() or poster.stat().st_size == 0:
        # Seeking from the end can miss on clips shorter than the offset
        _run(poster_args(mp4, poster, from_end=False))
    return mp4, poster


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Argument list; defaults to `sys.argv[1:]`.

    Returns:
        0 on success, 1 if ffmpeg failed, 2 if ffmpeg is missing. Argparse usage
        errors also exit 2, as in any argparse CLI.
    """
    parser = argparse.ArgumentParser(description="Encode a recording for a walkthrough page.")
    parser.add_argument("src", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--max-width", type=int, default=1280)
    parser.add_argument("--start", type=float)
    parser.add_argument("--end", type=float)
    args = parser.parse_args(argv)

    if shutil.which("ffmpeg") is None:
        sys.stderr.write(
            "ffmpeg not found on PATH; install it (for example `brew install ffmpeg`)\n"
        )
        return 2

    try:
        mp4, poster = encode(
            args.src,
            args.out_dir,
            max_width=args.max_width,
            start=args.start,
            end=args.end,
        )
    except (EncodeError, ValueError) as exc:
        sys.stderr.write(f"{exc}\n")
        return 1

    sys.stdout.write(json.dumps({"mp4": str(mp4), "poster": str(poster)}) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
