"""Tests for the walkthrough skill's clip encoder (scripts/encode.py)."""

from __future__ import annotations

import shutil
import subprocess
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
def encode():
    """Load encode.py in-process."""
    return load_hook_module(SCRIPTS_DIR, "encode.py", "wt_encode")


def test_mp4_args_pins_web_safe_encoding(encode):
    # Given a webm source and default options
    # When the ffmpeg argv is built
    args = encode.mp4_args(Path("in.webm"), Path("out.mp4"))

    # Then it pins a web-safe, silent, fast-start H.264 encode
    assert args[0] == "ffmpeg"
    for flag in ("-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an"):
        assert flag in args
    assert "scale='min(iw,1280)':-2" in args


def test_mp4_args_trims_when_start_and_end_given(encode):
    # Given a start and end time
    # When the ffmpeg argv is built
    args = encode.mp4_args(Path("in.mov"), Path("o.mp4"), start=1.5, end=4.0)

    # Then both trim flags carry the values
    assert args[args.index("-ss") + 1] == "1.5"
    assert args[args.index("-to") + 1] == "4.0"


def test_mp4_args_omits_trim_flags_by_default(encode):
    # Given no start or end
    # When the ffmpeg argv is built
    args = encode.mp4_args(Path("in.mov"), Path("o.mp4"))

    # Then no trim flags appear
    assert "-ss" not in args
    assert "-to" not in args


def test_poster_args_takes_final_frame(encode):
    # Given an encoded mp4
    # When the poster argv is built
    args = encode.poster_args(Path("o.mp4"), Path("o.poster.png"))

    # Then it seeks from the end and grabs one frame
    assert "-sseof" in args
    assert "-frames:v" in args


def test_encode_rejects_output_overwriting_source(encode, tmp_path):
    # Given a source that is already out_dir/<stem>.mp4
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"")

    # When encoding into the same directory
    # Then it refuses rather than clobber the source
    with pytest.raises(ValueError, match="overwrite"):
        encode.encode(src, tmp_path)


def test_main_exits_2_when_ffmpeg_missing(encode, tmp_path, monkeypatch):
    # Given a PATH with no ffmpeg
    monkeypatch.setenv("PATH", str(tmp_path))

    # When the CLI runs
    # Then it exits 2
    assert encode.main([str(tmp_path / "a.webm"), "--out-dir", str(tmp_path / "o")]) == 2


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_encode_short_clip_still_gets_poster(encode, tmp_path):
    # Given a 0.3 s lavfi test clip
    src = tmp_path / "in.webm"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=0.3:size=320x240:rate=10",
            str(src),
        ],
        check=True,
    )

    # When encoded
    mp4, poster = encode.encode(src, tmp_path / "out")

    # Then both outputs exist and are non-empty
    assert mp4.name == "in.mp4"
    assert poster.name == "in.poster.png"
    assert mp4.stat().st_size > 0
    assert poster.stat().st_size > 0


def _stub_ffmpeg(tmp_path: Path, body: str) -> Path:
    """Write an executable fake `ffmpeg` into its own bin dir and return that dir."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "ffmpeg"
    stub.write_text(f"#!/bin/sh\n{body}\n")
    stub.chmod(0o755)
    return bin_dir


def test_main_exits_1_and_prints_stderr_when_ffmpeg_fails(encode, tmp_path, monkeypatch, capsys):
    # Given an ffmpeg that writes an error and exits 1
    bin_dir = _stub_ffmpeg(tmp_path, "echo 'boom: bad input' >&2\nexit 1")
    monkeypatch.setenv("PATH", str(bin_dir))

    # When the CLI runs
    code = encode.main([str(tmp_path / "a.webm"), "--out-dir", str(tmp_path / "o")])

    # Then it exits 1 and surfaces ffmpeg's stderr
    assert code == 1
    assert "boom: bad input" in capsys.readouterr().err


def test_encode_retries_poster_from_start_when_end_seek_yields_nothing(
    encode, tmp_path, monkeypatch
):
    # Given an ffmpeg that writes nothing for an end-seek poster but succeeds otherwise
    body = (
        'for a in "$@"; do last="$a"; done\n'
        'case " $* " in *" -sseof "*) exit 0;; esac\n'
        'echo data > "$last"'
    )
    bin_dir = _stub_ffmpeg(tmp_path, body)
    monkeypatch.setenv("PATH", str(bin_dir))
    src = tmp_path / "in.webm"
    src.write_bytes(b"x")

    # When encoded
    _, poster = encode.encode(src, tmp_path / "out")

    # Then the from-start retry produced the poster
    assert poster.stat().st_size > 0
