"""Tests for the walkthrough skill's xcresult screenshot extractor (scripts/xcresult_extract.py)."""

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

UUID_A = "1A2B3C4D-1A2B-1A2B-1A2B-1A2B3C4D5E6F"
UUID_B = "9F8E7D6C-9F8E-9F8E-9F8E-9F8E7D6C5B4A"


@pytest.fixture
def xc():
    """Load xcresult_extract.py in-process."""
    return load_hook_module(SCRIPTS_DIR, "xcresult_extract.py", "wt_xcresult")


def _manifest(*names: tuple[str, str]) -> list[dict]:
    return [
        {
            "testIdentifier": "UITests/testFlow()",
            "attachments": [
                {"exportedFileName": exported, "suggestedHumanReadableName": suggested}
                for exported, suggested in names
            ],
        }
    ]


def _stub_xcrun(bin_dir: Path, manifest: list[dict], *, code: int = 0) -> None:
    """Write an `xcrun` stub that only accepts the expected xcresulttool argv.

    The stub creates every exported file named in `manifest` plus manifest.json
    in the directory passed as --output-path.
    """
    files = " ".join(
        f"'{att['exportedFileName']}'" for test in manifest for att in test["attachments"]
    )
    script = f"""#!/bin/sh
[ "$1 $2 $3" = "xcresulttool export attachments" ] || exit 64
shift 3
path=""; out=""; filter=""
while [ $# -gt 0 ]; do
  case "$1" in
    --path) path="$2" ;;
    --output-path) out="$2" ;;
    --filter) filter="$2" ;;
    *) exit 65 ;;
  esac
  shift 2
done
[ -n "$path" ] && [ -n "$out" ] && [ -n "$filter" ] || exit 66
[ "$filter" = "*.png" ] || exit 67
[ {code} -eq 0 ] || {{ echo "boom" >&2; exit {code}; }}
for f in {files}; do printf png > "$out/$f"; done
printf %s {shlex.quote(json.dumps(manifest))} > "$out/manifest.json"
"""
    stub = bin_dir / "xcrun"
    stub.write_text(script)
    stub.chmod(0o755)


@pytest.fixture
def bin_dir(tmp_path, monkeypatch):
    """An empty directory that is the entire PATH."""
    bins = tmp_path / "bin"
    bins.mkdir()
    monkeypatch.setenv("PATH", str(bins))
    return bins


def test_clean_name_strips_xcode_suffix(xc):
    # Given an Xcode-suffixed attachment name
    # When cleaned
    # Then the suffix is gone and the name is lowercased and hyphenated
    assert xc.clean_name(f"03 Filter Applied_0_{UUID_A}.png") == "03-filter-applied.png"


def test_clean_name_without_suffix_just_sanitizes(xc):
    # Given a name that carries no Xcode suffix
    # When cleaned
    # Then it is only sanitized
    assert xc.clean_name("Home Screen!!.PNG") == "home-screen.png"


def test_plan_renames_dedupes_collisions(xc):
    # Given two attachments that clean to the same name
    manifest = _manifest(
        ("x1.png", f"step_0_{UUID_A}.png"),
        ("x2.png", f"step_1_{UUID_B}.png"),
        ("x3.png", f"step_2_{UUID_A}.png"),
    )

    # When renames are planned
    plan = xc.plan_renames(manifest)

    # Then collisions get -2, -3 and manifest order is kept
    assert plan == [("x1.png", "step.png"), ("x2.png", "step-2.png"), ("x3.png", "step-3.png")]


def test_plan_renames_empty_stem_falls_back_to_exported_name(xc):
    # Given a suggested name that is all punctuation
    manifest = _manifest((f"{UUID_A}.png", "!!!.png"))

    # When renames are planned
    plan = xc.plan_renames(manifest)

    # Then the exported file's sanitized stem is used
    assert plan == [(f"{UUID_A}.png", f"{UUID_A.lower()}.png")]


def test_extract_uses_stubbed_xcresulttool(xc, bin_dir, tmp_path):
    # Given a stub xcrun that exports two PNG files and a manifest
    manifest = _manifest(
        ("a.png", f"01 Home_0_{UUID_A}.png"),
        ("b.png", f"02 Detail_0_{UUID_B}.png"),
    )
    _stub_xcrun(bin_dir, manifest)
    out_dir = tmp_path / "media"
    out_dir.mkdir()

    # When extract runs
    result = xc.extract(tmp_path / "Test.xcresult", out_dir)

    # Then out_dir holds exactly the two renamed files
    assert [p.name for p in result] == ["01-home.png", "02-detail.png"]
    assert sorted(p.name for p in out_dir.iterdir()) == ["01-home.png", "02-detail.png"]


def test_extract_creates_missing_out_dir(xc, bin_dir, tmp_path):
    # Given an out_dir that does not exist yet
    _stub_xcrun(bin_dir, _manifest(("a.png", f"Home_0_{UUID_A}.png")))
    out_dir = tmp_path / "new" / "media"

    # When extract runs
    result = xc.extract(tmp_path / "Test.xcresult", out_dir)

    # Then it is created and filled
    assert result == [out_dir / "home.png"]


def test_main_prints_paths_and_exits_zero(xc, bin_dir, tmp_path, capsys):
    # Given a working stub
    _stub_xcrun(bin_dir, _manifest(("a.png", f"Home_0_{UUID_A}.png")))
    out_dir = tmp_path / "media"

    # When the CLI runs
    code = xc.main([str(tmp_path / "Test.xcresult"), "--out-dir", str(out_dir)])

    # Then one path per line is printed
    assert code == 0
    assert capsys.readouterr().out == f"{out_dir / 'home.png'}\n"


def test_main_exits_one_when_xcresulttool_fails(xc, bin_dir, tmp_path, capsys):
    # Given an xcrun stub that fails
    _stub_xcrun(bin_dir, _manifest(("a.png", "Home.png")), code=3)

    # When the CLI runs
    code = xc.main([str(tmp_path / "Test.xcresult"), "--out-dir", str(tmp_path / "media")])

    # Then it exits 1 with the tool's stderr surfaced and nothing printed
    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert "boom" in captured.err


def test_main_exits_one_when_xcrun_missing(xc, bin_dir, tmp_path, capsys):
    # Given no xcrun on PATH
    # When the CLI runs
    code = xc.main([str(tmp_path / "Test.xcresult"), "--out-dir", str(tmp_path / "media")])

    # Then it exits 1 without a traceback
    assert code == 1
    assert "xcrun" in capsys.readouterr().err


def test_extract_overwrites_same_name_and_keeps_unrelated(xc, bin_dir, tmp_path):
    # Given an out_dir already holding home.png and an unrelated file
    _stub_xcrun(bin_dir, _manifest(("a.png", f"Home_0_{UUID_A}.png")))
    out_dir = tmp_path / "media"
    out_dir.mkdir()
    (out_dir / "home.png").write_text("old")
    (out_dir / "notes.txt").write_text("keep")

    # When extract runs
    xc.extract(tmp_path / "Test.xcresult", out_dir)

    # Then home.png is replaced and notes.txt is untouched
    assert (out_dir / "home.png").read_text() == "png"
    assert (out_dir / "notes.txt").read_text() == "keep"


def test_plan_renames_extensionless_name_takes_exported_extension(xc):
    # Given a suggested name without an extension
    # When renames are planned
    # Then the exported file's extension is appended
    assert xc.plan_renames(_manifest(("a.png", "Home"))) == [("a.png", "home.png")]


def test_plan_renames_dedupes_across_tests(xc):
    # Given two tests that both produce step.png
    manifest = [
        {
            "testIdentifier": "T/a",
            "attachments": _manifest(("x1.png", "step.png"))[0]["attachments"],
        },
        {
            "testIdentifier": "T/b",
            "attachments": _manifest(("x2.png", "step.png"))[0]["attachments"],
        },
    ]

    # When renames are planned
    # Then the second gets -2
    assert [n for _, n in xc.plan_renames(manifest)] == ["step.png", "step-2.png"]


def test_plan_renames_counter_ignores_dots_inside_stem(xc):
    # Given colliding names with a dot mid-name and no extension-like tail
    manifest = _manifest(("a.png", "step-1.5-home.png"), ("b.png", "step-1.5-home.png"))

    # When renames are planned
    # Then the counter lands before the real extension
    assert [n for _, n in xc.plan_renames(manifest)] == ["step-1.5-home.png", "step-1.5-home-2.png"]


@pytest.mark.parametrize("suggested", ["../x.png", "..\\x.png", "/etc/x.png", "a/../../x.png"])
def test_extract_targets_stay_inside_out_dir(xc, bin_dir, tmp_path, suggested):
    # Given hostile suggested and exported names
    _stub_xcrun(bin_dir, _manifest(("a.png", suggested)))
    manifest = _manifest(("../a.png", suggested))
    out_dir = tmp_path / "media"

    # When planned and extracted
    plan = xc.plan_renames(manifest)
    result = xc.extract(tmp_path / "Test.xcresult", out_dir)

    # Then every target stays inside out_dir
    assert all("/" not in final and "\\" not in final and final != ".." for _, final in plan)
    assert all(p.resolve().parent == out_dir.resolve() for p in result)


def _stub_raw_manifest(bin_dir: Path, body: str, *, files: str = "") -> None:
    script = f"""#!/bin/sh
shift 3
while [ $# -gt 0 ]; do
  [ "$1" = "--output-path" ] && out="$2"
  shift 2
done
for f in {files}; do printf png > "$out/$f"; done
{f'printf %s {shlex.quote(body)} > "$out/manifest.json"' if body else ""}
"""
    stub = bin_dir / "xcrun"
    stub.write_text(script)
    stub.chmod(0o755)


def test_extract_fails_without_manifest(xc, bin_dir, tmp_path):
    # Given an export that wrote no manifest.json
    _stub_raw_manifest(bin_dir, "")

    # When extract runs
    # Then it raises XcresultError
    with pytest.raises(xc.XcresultError, match="manifest"):
        xc.extract(tmp_path / "Test.xcresult", tmp_path / "media")


def test_extract_fails_on_non_list_manifest(xc, bin_dir, tmp_path):
    # Given a manifest that is a JSON object
    _stub_raw_manifest(bin_dir, "{}")

    # When extract runs
    # Then it raises XcresultError
    with pytest.raises(xc.XcresultError, match="not a list"):
        xc.extract(tmp_path / "Test.xcresult", tmp_path / "media")


def test_extract_fails_and_writes_nothing_when_a_file_is_missing(xc, bin_dir, tmp_path):
    # Given a manifest listing a.png and ghost.png but only a.png exported
    manifest = _manifest(("a.png", "A.png"), ("ghost.png", "Ghost.png"))
    _stub_raw_manifest(bin_dir, json.dumps(manifest), files="a.png")
    out_dir = tmp_path / "media"

    # When extract runs
    # Then it raises and leaves no partial output
    with pytest.raises(xc.XcresultError, match=r"ghost\.png"):
        xc.extract(tmp_path / "Test.xcresult", out_dir)
    assert not out_dir.exists() or not list(out_dir.iterdir())


@pytest.mark.parametrize(
    "manifest",
    [
        ["not-a-dict"],
        [{"testIdentifier": "T", "attachments": None}],
        [{"testIdentifier": "T", "attachments": [{"suggestedHumanReadableName": "a.png"}]}],
        [{"testIdentifier": "T", "attachments": ["x"]}],
        [{"testIdentifier": "T", "attachments": [{"exportedFileName": ""}]}],
    ],
)
def test_plan_renames_rejects_malformed_entries(xc, manifest):
    # Given a malformed manifest
    # When renames are planned
    # Then XcresultError is raised, not KeyError/TypeError/AttributeError
    with pytest.raises(xc.XcresultError):
        xc.plan_renames(manifest)


def test_main_warns_on_zero_attachments(xc, bin_dir, tmp_path, capsys):
    # Given a manifest with no attachments
    _stub_raw_manifest(bin_dir, "[]")

    # When the CLI runs
    code = xc.main([str(tmp_path / "Test.xcresult"), "--out-dir", str(tmp_path / "media")])

    # Then it exits 0 with a one-line warning on stderr and nothing on stdout
    captured = capsys.readouterr()
    assert code == 0
    assert captured.out == ""
    assert captured.err.count("\n") == 1
    assert "no attachments" in captured.err


@pytest.mark.parametrize(
    ("suggested", "expected"),
    [("step-1.5", "step-1.5.png"), ("login-1.0", "login-1.0.png"), ("v2.1", "v2.1.png")],
)
def test_plan_renames_version_like_name_still_gets_extension(xc, suggested, expected):
    # Given a suggested name whose tail looks like a version, not an extension
    # When renames are planned
    # Then the exported extension is appended
    assert xc.plan_renames(_manifest(("a.png", suggested))) == [("a.png", expected)]


def test_plan_renames_dedupes_version_like_names(xc):
    # Given two colliding version-like names
    manifest = _manifest(("a.png", "step-1.5"), ("b.png", "step-1.5"))

    # When renames are planned
    # Then the counter goes before the extension, not inside the version
    assert [n for _, n in xc.plan_renames(manifest)] == ["step-1.5.png", "step-1.5-2.png"]
