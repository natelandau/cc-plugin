#!/usr/bin/env -S uv run --script

# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///

"""Pull XCUITest screenshot attachments out of an Xcode `.xcresult` bundle.

Usage: xcresult_extract.py XCRESULT --out-dir DIR [--filter GLOB]

Exports the attachments with `xcrun xcresulttool`, strips the suffix Xcode
appends to each name, and copies them into DIR with readable names. Prints one
path per line. Exit codes: 0 on success, 1 when xcresulttool fails.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

_TIMEOUT = 300
# Xcode appends `_<index>_<uuid>` before the extension of each attachment name
_XCODE_SUFFIX = re.compile(r"_\d+_[0-9A-Fa-f-]{36}(?=\.\w+$)")
# Requiring a letter keeps version-like tails ("step-1.5", "v2.1") from reading as extensions
_EXTENSION = re.compile(r"\.(?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]{1,5}$")
_UNSAFE = re.compile(r"[^a-z0-9.-]+")


class XcresultError(Exception):
    """The export could not produce attachments."""


def _sanitize(text: str) -> str:
    return _UNSAFE.sub("-", text.lower())


def clean_name(suggested: str) -> str:
    """Turn an Xcode attachment name into a readable, filesystem-safe one.

    Args:
        suggested: A `suggestedHumanReadableName` from the export manifest.

    Returns:
        The name without Xcode's suffix, lowercased, with runs of characters
        outside `[a-z0-9.-]` replaced by `-`. May be empty if nothing survives.
    """
    stripped = _XCODE_SUFFIX.sub("", suggested)
    path = PurePosixPath(stripped)
    stem = _sanitize(path.stem).strip("-.")
    suffix = _sanitize(path.suffix).strip("-")
    if not stem:
        return ""
    return f"{stem}.{suffix.lstrip('.')}" if suffix.lstrip(".") else stem


def _split_ext(name: str) -> tuple[str, str]:
    """Split off a trailing extension, ignoring dots inside the stem ("step-1.5-home")."""
    match = _EXTENSION.search(name)
    if match is None:
        return name, ""
    return name[: match.start()], match.group()


def _final_name(attachment: dict[str, Any]) -> str:
    exported = attachment["exportedFileName"]
    name = clean_name(str(attachment.get("suggestedHumanReadableName", "")))
    exported_path = PurePosixPath(exported)
    exported_ext = _sanitize(exported_path.suffix).lstrip(".-")
    if not name:
        # A name with no usable characters would collide or be hidden
        name = _sanitize(exported_path.stem).strip("-.") or "attachment"
    if not _split_ext(name)[1] and exported_ext:
        name = f"{name}.{exported_ext}"
    return name


def _attachments(manifest: list[Any]) -> list[dict[str, Any]]:
    """Flatten and validate the manifest so malformed entries fail with a clear error."""
    flat: list[dict[str, Any]] = []
    for index, test in enumerate(manifest):
        if not isinstance(test, dict):
            msg = f"manifest entry {index} is not an object: {test!r}"
            raise XcresultError(msg)
        attachments = test.get("attachments", [])
        if not isinstance(attachments, list):
            msg = f"manifest entry {index} has non-list attachments: {attachments!r}"
            raise XcresultError(msg)
        for attachment in attachments:
            if not isinstance(attachment, dict) or not isinstance(
                attachment.get("exportedFileName"), str
            ):
                msg = f"manifest entry {index} has an attachment without exportedFileName: {attachment!r}"
                raise XcresultError(msg)
            if not attachment["exportedFileName"]:
                msg = f"manifest entry {index} has an empty exportedFileName"
                raise XcresultError(msg)
            flat.append(attachment)
    return flat


def plan_renames(manifest: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """Plan the final file name for every attachment across all tests.

    Colliding names get `-2`, `-3` before the extension so no screenshot is
    overwritten when tests reuse step names.

    Args:
        manifest: Parsed `manifest.json` from `xcresulttool export attachments`.

    Returns:
        `(exportedFileName, final_name)` pairs in manifest order.

    Raises:
        XcresultError: If an entry is malformed.
    """
    used: set[str] = set()
    plan: list[tuple[str, str]] = []
    for attachment in _attachments(manifest):
        name = _final_name(attachment)
        candidate = name
        stem, ext = _split_ext(name)
        count = 1
        while candidate in used:
            count += 1
            candidate = f"{stem}-{count}{ext}"
        used.add(candidate)
        plan.append((attachment["exportedFileName"], candidate))
    return plan


def extract(xcresult: Path, out_dir: Path, *, filter_glob: str = "*.png") -> list[Path]:
    """Export screenshots from a result bundle into `out_dir` with readable names.

    Args:
        xcresult: Path to the `.xcresult` bundle.
        out_dir: Destination directory; created if missing.
        filter_glob: Attachment filter passed to xcresulttool.

    Existing files in `out_dir` with the same final name are overwritten so
    re-runs are idempotent; other files are left alone. Every exported file is
    checked before any copy, so a failure leaves `out_dir` untouched.

    Returns:
        The copied files, sorted by path.

    Raises:
        XcresultError: If xcresulttool is missing, fails, or writes no readable manifest.
    """
    with tempfile.TemporaryDirectory() as tmp:
        export = Path(tmp)
        args = [
            "xcrun",
            "xcresulttool",
            "export",
            "attachments",
            "--path",
            str(xcresult),
            "--output-path",
            str(export),
            "--filter",
            filter_glob,
        ]
        try:
            proc = subprocess.run(  # noqa: S603
                args, capture_output=True, timeout=_TIMEOUT, check=False
            )
        except (OSError, subprocess.SubprocessError) as exc:
            msg = f"could not run xcrun xcresulttool: {exc}"
            raise XcresultError(msg) from exc
        if proc.returncode != 0:
            detail = proc.stderr.decode(errors="replace").strip()
            msg = f"xcresulttool exited {proc.returncode}: {detail}"
            raise XcresultError(msg)
        try:
            manifest = json.loads((export / "manifest.json").read_text())
        except (OSError, ValueError) as exc:
            msg = f"no readable manifest.json in the export of {xcresult}: {exc}"
            raise XcresultError(msg) from exc
        if not isinstance(manifest, list):
            msg = f"manifest.json is not a list (got {type(manifest).__name__})"
            raise XcresultError(msg)

        copies: list[tuple[Path, str]] = []
        for exported, final in plan_renames(manifest):
            source = export / PurePosixPath(exported).name
            if not source.is_file():
                msg = f"manifest lists {exported} but the export has no such file"
                raise XcresultError(msg)
            copies.append((source, final))

        out_dir.mkdir(parents=True, exist_ok=True)
        copied: list[Path] = []
        for source, final in copies:
            target = out_dir / final
            shutil.copyfile(source, target)
            copied.append(target)
    return sorted(copied)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Argument list; defaults to `sys.argv[1:]`.

    Returns:
        0 on success, 1 when the export fails.
    """
    parser = argparse.ArgumentParser(description="Extract screenshots from an .xcresult bundle.")
    parser.add_argument("xcresult", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--filter", default="*.png", dest="filter_glob")
    args = parser.parse_args(argv)

    try:
        paths = extract(args.xcresult, args.out_dir, filter_glob=args.filter_glob)
    except XcresultError as exc:
        sys.stderr.write(f"xcresult_extract: {exc}\n")
        return 1
    if not paths:
        sys.stderr.write("xcresult_extract: no attachments matched the filter\n")
    for path in paths:
        sys.stdout.write(f"{path}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
