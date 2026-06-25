"""Shared rule loading and matching for pattern-driven hooks.

Consolidates the per-hook TOML loaders that `protect_system`,
`protect_secrets`, and `stop_phrase_guard` used to each reimplement.
Every rule is an `[[<section>]]` table sharing one canonical schema:

- `id` (slug shown in block messages; optional for hooks that don't use it),
- `reason` (human-facing explanation), and
- exactly one matcher: a `pattern` (a single regex string **or a list of
  regex strings**, OR-combined, tested against a hook-chosen string) **or** a
  `conditions` list (each entry matches a named field with an operator,
  AND-combined across the list).

The single-`pattern` form preserves the original hooks' behavior; a list
`pattern` collapses many near-duplicate rules that share one `reason` into a
single rule (it matches if any pattern matches). The `conditions` form adds
multi-field matching as data, so a rule can require, say, a `file_path`
pattern *and* a `content` substring without new Python.

All regex matching is case-insensitive (`re.IGNORECASE`); the non-regex
string operators lowercase both sides to match that convention. Patterns
are compiled at load time so a malformed regex surfaces as a load error
rather than in the matching hot path.
"""

from __future__ import annotations

import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

# Required `[[rule]]` fields for the block hooks (protect_secrets,
# protect_system): a slug and a reason. Shared so the two hooks declare one
# vocabulary instead of two identical sets.
BLOCK_RULE_FIELDS: frozenset[str] = frozenset({"id", "reason"})

# Errors a rules-file read or parse can raise that the loaders treat as
# "this file is unusable": I/O failure, malformed TOML, a schema/type error
# from `parse_rules`, or a bad regex. One tuple so the built-in and
# project-overlay loaders catch exactly the same set and cannot drift.
RULES_LOAD_ERRORS: tuple[type[Exception], ...] = (
    OSError,
    tomllib.TOMLDecodeError,
    TypeError,
    ValueError,
    re.error,
)

# Operators valid in a condition. `regex_match` uses the pre-compiled
# pattern; the rest are plain (case-insensitive) string tests.
CONDITION_OPERATORS: frozenset[str] = frozenset(
    {"regex_match", "contains", "not_contains", "equals", "starts_with", "ends_with"}
)

_MATCHER_KEYS: frozenset[str] = frozenset({"pattern", "conditions"})
_CONDITION_KEYS: frozenset[str] = frozenset({"field", "operator", "pattern"})


@dataclass(frozen=True, slots=True)
class Condition:
    """A single field predicate within a rule's `conditions` list.

    `field` names the input the hook exposes (e.g. `file_path`, `command`),
    `operator` is one of `CONDITION_OPERATORS`, and `pattern` is the value
    tested against the field. `regex` holds the compiled pattern when the
    operator is `regex_match`, and is None otherwise.
    """

    field: str
    operator: str
    pattern: str
    regex: re.Pattern[str] | None


@dataclass(frozen=True, slots=True)
class Rule:
    """A loaded, compiled rule ready for first-match-wins iteration.

    A rule carries exactly one matcher: a non-empty `patterns` tuple for the
    `pattern` form (one entry for a string `pattern`, several for a list one,
    OR-combined), or a non-empty `conditions` tuple for the multi-field form.

    `match_field` names which input a `pattern` rule tests: when set, the
    patterns run against `fields[match_field]`; when None, they run against
    the hook's primary `text`. It lets one rule list mix rules that target
    different named inputs (e.g. a file path vs a command) without per-tool
    branching in the hook. It does not apply to the `conditions` form, where
    each condition names its own field.
    """

    id: str
    reason: str
    patterns: tuple[re.Pattern[str], ...] = ()
    conditions: tuple[Condition, ...] = ()
    match_field: str | None = None


def _require_str(entry: Mapping[str, object], key: str, where: str) -> str:
    """Return entry[key] as a str or raise TypeError naming the offender.

    The TOML loader yields `object`-typed values, so every required field
    is unwrapped through this helper before reaching a dataclass. Keeps the
    type narrowing in one place and gives a uniform error shape.
    """
    value = entry[key]
    if not isinstance(value, str):
        msg = f"{where}.{key} must be a string, got {type(value).__name__}"
        raise TypeError(msg)
    return value


def _compile_regex(value: object, where: str) -> re.Pattern[str]:
    """Compile one regex string with the module-wide IGNORECASE flag.

    The single primitive behind every rule-file pattern (single `pattern`,
    list `pattern`, condition `pattern`, and the flat allowlist), so the
    "compile at load time, case-insensitive" convention lives in one place.
    """
    if not isinstance(value, str):
        msg = f"{where} must be a string, got {type(value).__name__}"
        raise TypeError(msg)
    return re.compile(value, re.IGNORECASE)


def _parse_conditions(raw: object, where: str) -> tuple[Condition, ...]:
    """Validate and compile a rule's `conditions` array.

    Each condition must be a table with exactly `field`, `operator`, and
    `pattern`. `regex_match` patterns are compiled here so a bad regex
    raises at load time.
    """
    if not isinstance(raw, list) or not raw:
        msg = f"{where}.conditions must be a non-empty array of tables"
        raise TypeError(msg)
    parsed: list[Condition] = []
    for idx, raw_cond in enumerate(raw):
        cwhere = f"{where}.conditions[{idx}]"
        if not isinstance(raw_cond, dict):
            msg = f"{cwhere} is not a table"
            raise TypeError(msg)
        cond = cast("Mapping[str, object]", raw_cond)
        keys = cond.keys()
        missing = _CONDITION_KEYS - keys
        if missing:
            msg = f"{cwhere} missing fields: {sorted(missing)}"
            raise ValueError(msg)
        extra = keys - _CONDITION_KEYS
        if extra:
            msg = f"{cwhere} has unexpected fields: {sorted(extra)}"
            raise ValueError(msg)
        operator = _require_str(cond, "operator", cwhere)
        if operator not in CONDITION_OPERATORS:
            msg = f"{cwhere} has unknown operator {operator!r}"
            raise ValueError(msg)
        pattern = _require_str(cond, "pattern", cwhere)
        parsed.append(
            Condition(
                field=_require_str(cond, "field", cwhere),
                operator=operator,
                pattern=pattern,
                regex=_compile_regex(pattern, cwhere) if operator == "regex_match" else None,
            )
        )
    return tuple(parsed)


def _compile_patterns(value: object, where: str) -> tuple[re.Pattern[str], ...]:
    """Compile a rule's `pattern` (a single regex string or a list of them).

    A list is OR-combined at match time: the rule fires if any pattern hits,
    which collapses many same-`reason` rules into one. Every pattern compiles
    here so a bad regex surfaces as a load error, not in the matching hot path.
    """
    items = value if isinstance(value, list) else [value]
    if not items:
        msg = f"{where}.pattern must not be an empty list"
        raise ValueError(msg)
    return tuple(_compile_regex(item, f"{where}.pattern[{idx}]") for idx, item in enumerate(items))


def parse_rules(
    data: Mapping[str, object],
    section: str,
    *,
    required: frozenset[str],
    optional: frozenset[str] = frozenset(),
) -> tuple[Rule, ...]:
    """Validate one `[[<section>]]` array from parsed TOML into Rules.

    Every entry must carry the `required` fields (besides its matcher),
    exactly one matcher (`pattern` or `conditions`), and no field outside
    `required | optional | {pattern, conditions, field}`. A `pattern` may be
    a single regex string or a list of them (OR-combined). An optional
    `field` selects which named input a `pattern` rule matches (invalid
    alongside `conditions`). Errors name the offending entry so a TOML typo
    surfaces clearly instead of producing a malformed Rule.

    Args:
        data: The parsed TOML mapping.
        section: The array-of-tables key to read (e.g. "rule", "violation").
        required: Field names every entry must provide, besides the matcher.
        optional: Field names entries may provide.

    Returns:
        Rules in declaration order, ready for first-match-wins iteration.
    """
    raw_entries = data.get(section)
    if not isinstance(raw_entries, list):
        msg = f"missing or non-array '{section}' section"
        raise TypeError(msg)
    allowed = required | optional | _MATCHER_KEYS | {"field"}
    rules: list[Rule] = []
    for idx, raw_entry in enumerate(raw_entries):
        where = f"{section}[{idx}]"
        if not isinstance(raw_entry, dict):
            msg = f"{where} is not a table"
            raise TypeError(msg)
        # tomllib types entries as dict[str, Any]; cast to a covariant
        # Mapping so _require_str can read fields without ty rejecting the
        # invariant dict generic.
        entry = cast("Mapping[str, object]", raw_entry)
        keys = entry.keys()
        missing = required - keys
        if missing:
            msg = f"{where} missing fields: {sorted(missing)}"
            raise ValueError(msg)
        extra = keys - allowed
        if extra:
            msg = f"{where} has unexpected fields: {sorted(extra)}"
            raise ValueError(msg)
        matcher_keys = keys & _MATCHER_KEYS
        if len(matcher_keys) != 1:
            msg = f"{where} must have exactly one of 'pattern' or 'conditions'"
            raise ValueError(msg)
        match_field = _require_str(entry, "field", where) if "field" in keys else None
        if match_field is not None and "conditions" in matcher_keys:
            msg = f"{where} sets 'field' but uses 'conditions'; 'field' applies only to 'pattern'"
            raise ValueError(msg)
        if "conditions" in matcher_keys:
            patterns: tuple[re.Pattern[str], ...] = ()
            conditions = _parse_conditions(entry["conditions"], where)
        else:
            patterns = _compile_patterns(entry["pattern"], where)
            conditions = ()
        rules.append(
            Rule(
                id=_require_str(entry, "id", where) if "id" in keys else "",
                reason=_require_str(entry, "reason", where),
                patterns=patterns,
                conditions=conditions,
                match_field=match_field,
            )
        )
    return tuple(rules)


def read_toml(path: Path) -> dict[str, object]:
    """Parse a TOML rules file, raising on any read or decode failure.

    Callers run inside a hook `main()` that catches `OSError` and
    `tomllib.TOMLDecodeError` to exit 1 non-blocking, so failures are not
    swallowed here.
    """
    with path.open("rb") as fh:
        return tomllib.load(fh)


def load_rules(
    path: Path,
    section: str,
    *,
    required: frozenset[str],
    optional: frozenset[str] = frozenset(),
) -> tuple[Rule, ...]:
    """Read a TOML file and parse one `[[<section>]]` array into Rules.

    Convenience wrapper over `parse_rules` for hooks that read a single
    section. Hooks needing several sections from one file should call
    `read_toml` once and `parse_rules`/`parse_pattern_list` per section.
    """
    return parse_rules(read_toml(path), section, required=required, optional=optional)


PROJECT_RULES_SUBDIR: tuple[str, ...] = (".claude", "natelandau-toolkit")


def project_rules_path(filename: str, *, project_dir: str | None) -> Path | None:
    """Resolve an optional per-project rules file mirroring a built-in's name.

    Projects extend a hook's built-in rules by dropping a file of the same
    basename under `<project_dir>/.claude/natelandau-toolkit/`. Return that
    path when `project_dir` is set and the file exists, else None.
    """
    if not project_dir:
        return None
    path = Path(project_dir, *PROJECT_RULES_SUBDIR, filename)
    return path if path.exists() else None


def load_project_rules(
    filename: str,
    section: str,
    *,
    required: frozenset[str],
    optional: frozenset[str] = frozenset(),
    project_dir: str | None,
) -> tuple[Rule, ...]:
    """Load a project's additive rules for a hook, failing open to ().

    Per-project rules can only *add* blocks, never weaken built-ins, so the
    caller appends the result to its built-in rule tuple. A malformed project
    file is caught here: a one-line warning goes to stderr and () is returned,
    so a project typo never disables the hook's built-in rules nor wedges the
    tool call. Return () when no project file is present.
    """
    path = project_rules_path(filename, project_dir=project_dir)
    if path is None:
        return ()
    try:
        return load_rules(path, section, required=required, optional=optional)
    except RULES_LOAD_ERRORS as exc:
        print(f"natelandau-toolkit: ignoring project rules {path}: {exc}", file=sys.stderr)  # noqa: T201
        return ()


def load_all_rules(
    rules_file: Path,
    section: str,
    *,
    required: frozenset[str],
    optional: frozenset[str] = frozenset(),
    project_dir: str | None,
    label: str,
) -> tuple[Rule, ...]:
    """Load a hook's built-in rules plus its additive per-project rules.

    The single entry every rule-driven hook shares: read `rules_file`'s
    `[[section]]` (the built-in rules) and append the project's additive
    rules. A malformed *built-in* file raises, after a `<label>: ...` stderr
    note so the diagnostic names the failing hook; the dispatcher swallows
    the raise and the built-ins reload next invocation. Project rules fail
    open inside `load_project_rules`, so a project typo never disables the
    built-ins. Returns built-in-then-project in declaration order.

    Args:
        rules_file: Path to the hook's built-in `<hook>.rules.toml`.
        section: The `[[<section>]]` array to read (e.g. "rule", "trigger").
        required: Field names every entry must provide, besides the matcher.
        optional: Field names entries may provide.
        project_dir: Project root for the additive per-project file, or None.
        label: Hook name prefixed to the built-in load-failure warning.
    """

    def parse(path: Path) -> tuple[Rule, ...]:
        return load_rules(path, section, required=required, optional=optional)

    def parse_builtin(path: Path) -> tuple[Rule, ...]:
        try:
            return parse(path)
        except RULES_LOAD_ERRORS as exc:
            print(f"{label}: failed to load {path.name}: {exc}", file=sys.stderr)  # noqa: T201
            raise

    return with_project_overlay(
        rules_file,
        project_dir=project_dir,
        parse=parse,
        parse_builtin=parse_builtin,
        combine=lambda builtin, project: (*builtin, *project),
    )


def with_project_overlay[T](
    builtin_path: Path,
    *,
    project_dir: str | None,
    parse: Callable[[Path], T],
    combine: Callable[[T, T], T],
    parse_builtin: Callable[[Path], T] | None = None,
) -> T:
    """Overlay a project's additive rules onto a hook's built-in rules, failing open.

    The one fail-open project-overlay engine every rule-driven hook shares,
    shape-agnostic over the rule type: `load_all_rules` uses it for the
    `[[<section>]]` Rule tuple, `config_protection` for its name lists. Reads
    the built-in file via `parse_builtin(builtin_path)` (defaulting to `parse`;
    its errors propagate to the driver); when a per-project file of the same
    basename exists, parses it with `parse` and `combine`s it on top. A
    malformed *project* file is caught here, with the same one-line stderr
    warning and caught-exception set as `load_project_rules`, and the built-in
    result is returned unchanged, so a project typo never disables a built-in.

    Args:
        builtin_path: Path to the hook's built-in `<hook>.rules.toml`.
        project_dir: Project root for the additive per-project file, or None.
        parse: Reads a project rules file at a path into the hook's rule shape.
        combine: Folds the project rules onto the built-in rules (additive).
        parse_builtin: Reads the built-in file; defaults to `parse`. Supply a
            distinct reader when a built-in load failure needs its own handling
            (e.g. a hook-labeled stderr note) before the error propagates.
    """
    builtin = (parse_builtin or parse)(builtin_path)
    proj_path = project_rules_path(builtin_path.name, project_dir=project_dir)
    if proj_path is None:
        return builtin
    try:
        project = parse(proj_path)
    except RULES_LOAD_ERRORS as exc:
        print(f"natelandau-toolkit: ignoring project rules {proj_path}: {exc}", file=sys.stderr)  # noqa: T201
        return builtin
    return combine(builtin, project)


def parse_pattern_list(data: Mapping[str, object], key: str) -> tuple[re.Pattern[str], ...]:
    """Compile a flat TOML array of regex strings (e.g. an allowlist).

    Each entry is compiled with `re.IGNORECASE`. Raises if the key is
    missing, not an array, or holds a non-string entry.
    """
    raw = data.get(key)
    if not isinstance(raw, list):
        msg = f"missing or non-array '{key}' section"
        raise TypeError(msg)
    return tuple(_compile_regex(entry, f"{key}[{idx}]") for idx, entry in enumerate(raw))


# Non-regex string operators, keyed by name. Each takes the (lowercased)
# field value and condition pattern. `regex_match` is handled separately
# because it uses the pre-compiled pattern, not a plain string test.
_STRING_OPS: dict[str, Callable[[str, str], bool]] = {
    "contains": lambda value, pat: pat in value,
    "not_contains": lambda value, pat: pat not in value,
    "equals": lambda value, pat: value == pat,
    "starts_with": lambda value, pat: value.startswith(pat),
    "ends_with": lambda value, pat: value.endswith(pat),
}


def _condition_matches(cond: Condition, fields: Mapping[str, str]) -> bool:
    """Return whether one condition holds against the available fields.

    A field the hook did not supply is treated as the empty string, so a
    `contains`/`regex_match` condition simply does not match it (and a
    `not_contains` condition does).
    """
    value = fields.get(cond.field, "")
    if cond.operator == "regex_match":
        return cond.regex is not None and cond.regex.search(value) is not None
    op = _STRING_OPS[cond.operator]  # operator validated at load time
    return op(value.lower(), cond.pattern.lower())


def rule_matches(rule: Rule, *, text: str, fields: Mapping[str, str]) -> bool:
    """Return whether a rule matches, by its matcher form.

    A `pattern` rule tests its compiled patterns against `fields[match_field]`
    when the rule names a `match_field`, else against `text` (the primary
    string the hook chose), matching if any pattern hits (OR-combined). A
    `conditions` rule requires every condition to hold against `fields`.
    """
    if rule.conditions:
        return all(_condition_matches(cond, fields) for cond in rule.conditions)
    if not rule.patterns:
        return False
    haystack = fields.get(rule.match_field, "") if rule.match_field is not None else text
    return any(pattern.search(haystack) is not None for pattern in rule.patterns)


def first_match(
    rules: tuple[Rule, ...],
    *,
    text: str = "",
    fields: Mapping[str, str] | None = None,
) -> Rule | None:
    """Return the first rule that matches, in declaration order.

    Rules are tested first-match-wins. `text` feeds single-pattern rules;
    `fields` feeds conditions rules.
    """
    field_map = fields or {}
    for rule in rules:
        if rule_matches(rule, text=text, fields=field_map):
            return rule
    return None
