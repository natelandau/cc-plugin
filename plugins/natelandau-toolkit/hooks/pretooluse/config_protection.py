#!/usr/bin/env -S uv run --script

# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///

"""PreToolUse hook: blocks edits that weaken linter/formatter/typechecker config.

When a quality check fails, the right fix is almost always to change the
code, not to loosen the rule that caught it. This hook blocks Edit/Write
modifications of existing config files (`ruff.toml`, `.pre-commit-config.yaml`,
`mypy.ini`, ...) and of the linter/typechecker `[tool.*]` tables inside
`pyproject.toml`.

Two non-obvious carve-outs keep it from getting in the way:

- **First-time creation passes through.** Bootstrapping a config that does
  not exist yet is allowed; only *modifying* an existing one is blocked.
  Existence is probed with `lstat` (symlink-aware) so a symlink to a
  missing target is not mistaken for an existing file.
- **`pyproject.toml` is inspected, not blanket-blocked.** Only changes to a
  protected `[tool.<linter>]` table are blocked. Dependency, build-system,
  project-metadata, classifier, and test-config edits pass through, so
  agents can still manage the package. For an `Edit` the proposed
  `old_string -> new_string` substitution is applied in memory and the
  before/after TOML are compared table-by-table; for a `Write` the new
  `content` is compared against the file on disk.

Rule data (the protected filenames and `[tool.*]` prefixes) lives in
`config_protection.rules.toml` next to this file; the diffing logic lives
here. Per the never-wedge contract, any failure to read rules or analyze
input fails open (the standalone entry exits 1 non-blocking; the
dispatcher swallows exceptions).
"""

from __future__ import annotations

import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from lib.io import Decision
from lib.rules import project_rules_path, read_toml

if TYPE_CHECKING:
    from lib.config import Config

ID = "config-protection"
RULES_FILE = Path(__file__).parent / "config_protection.rules.toml"
PYPROJECT = "pyproject.toml"

_OVERRIDE_HINT = (
    "Fix the code rather than weakening the rule. To override intentionally, "
    "disable `config-protection` in natelandau-toolkit.toml or edit the file "
    "outside Claude Code."
)


@dataclass(frozen=True, slots=True)
class RuleSet:
    """Protected-name data loaded from the sibling TOML.

    `protected_files` are basenames blocked when modified (creation is
    allowed). `protected_pyproject_tables` are dotted `[tool.*]` prefixes
    whose existing tables are protected inside `pyproject.toml`.
    """

    protected_files: frozenset[str]
    protected_pyproject_tables: tuple[str, ...]


def _require_str_list(raw: object, section: str) -> list[str]:
    """Return raw as a list of strings, or [] when the section is absent.

    A missing section means "no entries" so a project file can supply just
    one of the two lists. A present-but-wrong-typed value still raises.
    """
    if raw is None:
        return []
    if not isinstance(raw, list):
        msg = f"'{section}' must be an array of strings"
        raise TypeError(msg)
    out: list[str] = []
    for idx, item in enumerate(raw):
        if not isinstance(item, str):
            msg = f"{section}[{idx}] must be a string, got {type(item).__name__}"
            raise TypeError(msg)
        out.append(item)
    return out


def _load_rules(path: Path) -> RuleSet:
    """Parse the rules TOML into an immutable RuleSet.

    A typo in the lists surfaces as a clear load error here rather than as
    silently-missing protection at match time. Reads through the shared
    `rules.read_toml` so the canonical reader's hardening applies, matching
    the other rule-driven hooks.
    """
    data = read_toml(path)
    return RuleSet(
        protected_files=frozenset(
            _require_str_list(data.get("protected_files"), "protected_files")
        ),
        protected_pyproject_tables=tuple(
            _require_str_list(data.get("protected_pyproject_tables"), "protected_pyproject_tables")
        ),
    )


def _merged_rules(project_dir: str | None) -> RuleSet:
    """Combine built-in protected names with a project's additive entries.

    Project rules can only add protected files/tables. A malformed project
    file fails open (warn + ignore) so it never disables the built-ins.
    """
    builtin = _load_rules(RULES_FILE)
    proj_path = project_rules_path(RULES_FILE.name, project_dir=project_dir)
    if proj_path is None:
        return builtin
    try:
        project = _load_rules(proj_path)
    except (OSError, tomllib.TOMLDecodeError, TypeError, ValueError) as exc:
        print(f"natelandau-toolkit: ignoring project rules {proj_path}: {exc}", file=sys.stderr)  # noqa: T201
        return builtin
    return RuleSet(
        protected_files=builtin.protected_files | project.protected_files,
        protected_pyproject_tables=(
            *builtin.protected_pyproject_tables,
            *project.protected_pyproject_tables,
        ),
    )


def _exists(path: Path) -> bool:
    """Return whether path exists, without following symlinks.

    Uses `lstat` so the "allow first-time creation, block modification"
    gate is not fooled by a symlink whose target is missing.
    """
    try:
        path.lstat()
    except OSError:
        return False
    return True


def _read_text(path: Path) -> str | None:
    """Read path as UTF-8, or None when it cannot be read."""
    try:
        return path.read_text(encoding="utf-8")
    except OSError, UnicodeDecodeError:
        return None


def _parse_toml(text: str) -> dict[str, Any] | None:
    """Parse TOML text, or None when it is malformed."""
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError, ValueError:
        return None


def _apply_edit(text: str, old_string: str, new_string: str, *, replace_all: bool) -> str | None:
    """Apply an Edit's substitution to text, mirroring the Edit tool.

    Returns None when `old_string` is empty or absent, so a malformed Edit
    (which the Edit tool itself will reject) is not analyzed.
    """
    if not old_string or old_string not in text:
        return None
    if replace_all:
        return text.replace(old_string, new_string)
    return text.replace(old_string, new_string, 1)


def _get_table(data: dict[str, Any], dotted: str) -> Any | None:
    """Return the subtree of data at a dotted key path, or None if absent."""
    node: Any = data
    for key in dotted.split("."):
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


def _changed_tables(
    old: dict[str, Any], new: dict[str, Any], prefixes: tuple[str, ...]
) -> list[str]:
    """Return protected table prefixes whose existing content changed.

    A prefix absent from `old` is treated as bootstrap (allowed), so only
    tables that existed before and differ afterward are reported.
    """
    changed: list[str] = []
    for prefix in prefixes:
        old_sub = _get_table(old, prefix)
        if old_sub is None:
            continue
        if old_sub != _get_table(new, prefix):
            changed.append(prefix)
    return changed


def _check_whole_file(path: Path) -> Decision | None:
    """Block modification of an existing protected config; allow creation."""
    if not _exists(path):
        return None
    return Decision(
        block=True,
        reason=(
            f"BLOCKED [config-protection]: Refusing to modify `{path.name}`, a "
            f"linter/formatter/typechecker config. {_OVERRIDE_HINT}"
        ),
    )


def _check_pyproject(
    tool_name: str, tool_input: dict[str, Any], path: Path, rules: RuleSet
) -> Decision | None:
    """Block edits that change a protected [tool.*] table in pyproject.toml.

    Creating pyproject.toml from scratch, edits whose `old_string` cannot be
    located, and unparsable TOML all fail open (return None): the hook only
    blocks when it can positively confirm a protected table changed.
    """
    if not rules.protected_pyproject_tables or not _exists(path):
        return None
    old_text = _read_text(path)
    if old_text is None:
        return None

    if tool_name == "Write":
        new_text = tool_input.get("content", "")
    else:  # Edit
        new_text = _apply_edit(
            old_text,
            tool_input.get("old_string", ""),
            tool_input.get("new_string", ""),
            replace_all=bool(tool_input.get("replace_all", False)),
        )
        if new_text is None:
            return None

    old_data = _parse_toml(old_text)
    new_data = _parse_toml(new_text)
    if old_data is None or new_data is None:
        return None

    changed = _changed_tables(old_data, new_data, rules.protected_pyproject_tables)
    if not changed:
        return None
    tables = ", ".join(f"[{prefix}]" for prefix in changed)
    return Decision(
        block=True,
        reason=(
            f"BLOCKED [config-protection]: Refusing to change the {tables} table(s) in "
            f"{PYPROJECT}, which hold linter/typechecker config. Dependency, build, and "
            f"metadata edits are allowed. {_OVERRIDE_HINT}"
        ),
    )


def evaluate(event: dict[str, Any], cfg: Config) -> Decision | None:
    """Return a block Decision for a config-weakening edit, else None."""
    tool_name = event.get("tool_name", "")
    if tool_name not in ("Edit", "Write"):
        return None
    tool_input = event.get("tool_input") or {}
    file_path = tool_input.get("file_path", "")
    if not file_path:
        return None

    rules = _merged_rules(cfg.project_dir)  # may raise on built-in only; caught by caller / main
    path = Path(file_path)
    if path.name == PYPROJECT:
        return _check_pyproject(tool_name, tool_input, path, rules)
    if path.name in rules.protected_files:
        return _check_whole_file(path)
    return None
