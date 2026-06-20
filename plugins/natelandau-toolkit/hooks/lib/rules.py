# plugins/natelandau-toolkit/hooks/lib/rules.py
"""Shared rule loading and matching for pattern-driven hooks.

Consolidates the per-hook TOML loaders that `protect_system`,
`protect_secrets`, and `stop_phrase_guard` used to each reimplement.
Every rule is an `[[<section>]]` table sharing one canonical schema:

- `id` (slug shown in block messages; optional for hooks that don't use it),
- `reason` (human-facing explanation),
- `level` (optional threshold tier: `critical` < `high` < `strict`), and
- exactly one matcher: a single `pattern` (regex tested against a
  hook-chosen string) **or** a `conditions` list (each entry matches a
  named field with an operator, AND-combined across the list).

The single-`pattern` form preserves the original hooks' behavior; the
`conditions` form adds multi-field matching as data, so a rule can require,
say, a `file_path` pattern *and* a `content` substring without new Python.

All regex matching is case-insensitive (`re.IGNORECASE`); the non-regex
string operators lowercase both sides to match that convention. Patterns
are compiled at load time so a malformed regex surfaces as a load error
rather than in the matching hot path.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path

LEVELS: dict[str, int] = {"critical": 1, "high": 2, "strict": 3}

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

    `level` gates whether the rule fires at the active threshold (None
    means "always eligible", used by hooks without thresholds). A rule
    carries exactly one matcher: `regex` for the single-`pattern` form, or
    a non-empty `conditions` tuple for the multi-field form.

    `match_field` names which input a single-`pattern` rule tests: when set,
    the regex runs against `fields[match_field]`; when None, it runs against
    the hook's primary `text`. It lets one rule list mix rules that target
    different named inputs (e.g. a file path vs a command) without per-tool
    branching in the hook. It does not apply to the `conditions` form, where
    each condition names its own field.
    """

    id: str
    reason: str
    level: str | None
    regex: re.Pattern[str] | None
    conditions: tuple[Condition, ...] = field(default_factory=tuple)
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
                regex=re.compile(pattern, re.IGNORECASE) if operator == "regex_match" else None,
            )
        )
    return tuple(parsed)


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
    `required | optional | {pattern, conditions, field}`. A `level`, when
    present, must be a known threshold. An optional `field` selects which
    named input a `pattern` rule matches (invalid alongside `conditions`).
    Errors name the offending entry so a TOML typo surfaces clearly instead
    of producing a malformed Rule.

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
        level = entry["level"] if "level" in keys else None
        if level is not None and (not isinstance(level, str) or level not in LEVELS):
            msg = f"{where} has unknown level {level!r}"
            raise ValueError(msg)
        if "conditions" in matcher_keys:
            regex = None
            conditions = _parse_conditions(entry["conditions"], where)
        else:
            regex = re.compile(_require_str(entry, "pattern", where), re.IGNORECASE)
            conditions = ()
        rules.append(
            Rule(
                id=_require_str(entry, "id", where) if "id" in keys else "",
                reason=_require_str(entry, "reason", where),
                level=level,
                regex=regex,
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


def parse_pattern_list(data: Mapping[str, object], key: str) -> tuple[re.Pattern[str], ...]:
    """Compile a flat TOML array of regex strings (e.g. an allowlist).

    Each entry is compiled with `re.IGNORECASE`. Raises if the key is
    missing, not an array, or holds a non-string entry.
    """
    raw = data.get(key)
    if not isinstance(raw, list):
        msg = f"missing or non-array '{key}' section"
        raise TypeError(msg)
    compiled: list[re.Pattern[str]] = []
    for idx, entry in enumerate(raw):
        if not isinstance(entry, str):
            msg = f"{key}[{idx}] must be a string, got {type(entry).__name__}"
            raise TypeError(msg)
        compiled.append(re.compile(entry, re.IGNORECASE))
    return tuple(compiled)


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

    A single-`pattern` rule tests its regex against `fields[match_field]`
    when the rule names a `match_field`, else against `text` (the primary
    string the hook chose). A `conditions` rule requires every condition to
    hold against `fields`.
    """
    if rule.conditions:
        return all(_condition_matches(cond, fields) for cond in rule.conditions)
    if rule.regex is None:
        return False
    haystack = fields.get(rule.match_field, "") if rule.match_field is not None else text
    return rule.regex.search(haystack) is not None


def first_match(
    rules: tuple[Rule, ...],
    *,
    text: str = "",
    fields: Mapping[str, str] | None = None,
    threshold: int | None = None,
) -> Rule | None:
    """Return the first matching rule eligible at the active threshold.

    Rules are tested in declaration order (first-match-wins). When
    `threshold` is given, a rule whose `level` ranks above it is skipped;
    rules without a `level` are always eligible. `text` feeds single-pattern
    rules; `fields` feeds conditions rules.
    """
    field_map = fields or {}
    for rule in rules:
        if threshold is not None and rule.level is not None and LEVELS[rule.level] > threshold:
            continue
        if rule_matches(rule, text=text, fields=field_map):
            return rule
    return None
