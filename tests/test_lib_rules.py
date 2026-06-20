"""Unit tests for hooks/lib/rules.py: the shared loader and matcher.

Exercises parsing/validation of both rule forms (single `pattern` and
multi-field `conditions`), every condition operator, threshold gating, and
the flat allowlist parser. Rules are built by passing plain dicts straight
to `parse_rules`, so the parser is covered alongside the matcher.
"""

from __future__ import annotations

import importlib
import sys
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from pathlib import Path
    from types import ModuleType


@pytest.fixture
def rules(hooks_dir: Path) -> ModuleType:
    """Import lib.rules with the hooks dir on sys.path."""
    sys.path.insert(0, str(hooks_dir))
    try:
        return importlib.import_module("lib.rules")
    finally:
        sys.path.pop(0)


def _pattern_rule(**over: Any) -> dict[str, Any]:
    """Build a single-pattern rule table, overriding any field."""
    return {"id": "r1", "level": "high", "reason": "because", "pattern": "secret", **over}


def _conditions_rule(conditions: list[dict[str, str]], **over: Any) -> dict[str, Any]:
    """Build a conditions rule table with the given condition list."""
    return {"id": "c1", "level": "high", "reason": "because", "conditions": conditions, **over}


# --- parsing: single-pattern form ------------------------------------------


def test_parse_rules_single_pattern(rules: ModuleType) -> None:
    """Verify a single-pattern rule parses into a compiled regex Rule."""
    # Given one valid pattern rule
    data = {"rule": [_pattern_rule()]}

    # When parsing the section
    parsed = rules.parse_rules(data, "rule", required=frozenset({"id", "level", "reason"}))

    # Then one Rule with a compiled regex and no conditions is returned
    assert len(parsed) == 1
    assert parsed[0].id == "r1"
    assert parsed[0].regex is not None
    assert parsed[0].conditions == ()


def test_parse_rules_optional_id_defaults_blank(rules: ModuleType) -> None:
    """Verify an omitted optional id becomes the empty string."""
    # Given a rule with no id and id only optional
    data = {"violation": [{"reason": "stop", "pattern": "nope"}]}

    # When parsing with id optional
    parsed = rules.parse_rules(
        data, "violation", required=frozenset({"reason"}), optional=frozenset({"id"})
    )

    # Then the rule loads with a blank id
    assert parsed[0].id == ""


# --- parsing: validation errors --------------------------------------------


@pytest.mark.parametrize(
    ("entry", "exc"),
    [
        pytest.param({"id": "x", "level": "high", "reason": "r"}, ValueError, id="no-matcher"),
        pytest.param(
            {"id": "x", "level": "high", "reason": "r", "pattern": "p", "conditions": []},
            ValueError,
            id="two-matchers",
        ),
        pytest.param({"level": "high", "reason": "r", "pattern": "p"}, ValueError, id="missing-id"),
        pytest.param(
            {"id": "x", "level": "high", "reason": "r", "pattern": "p", "extra": "1"},
            ValueError,
            id="unknown-field",
        ),
        pytest.param(
            {"id": "x", "level": "nope", "reason": "r", "pattern": "p"},
            ValueError,
            id="unknown-level",
        ),
        pytest.param(
            {"id": 5, "level": "high", "reason": "r", "pattern": "p"},
            TypeError,
            id="non-string-field",
        ),
    ],
)
def test_parse_rules_rejects_bad_entry(
    rules: ModuleType, entry: dict[str, Any], exc: type[Exception]
) -> None:
    """Verify malformed rule entries raise a clear typed error."""
    # Given a section holding one malformed entry
    data = {"rule": [entry]}

    # When/Then parsing raises the expected error type
    with pytest.raises(exc):
        rules.parse_rules(data, "rule", required=frozenset({"id", "level", "reason"}))


def test_parse_rules_non_array_section(rules: ModuleType) -> None:
    """Verify a missing or non-array section raises TypeError."""
    # Given no 'rule' key
    data: dict[str, Any] = {}

    # When/Then parsing raises TypeError
    with pytest.raises(TypeError):
        rules.parse_rules(data, "rule", required=frozenset({"reason"}))


# --- parsing: conditions form ----------------------------------------------


def test_parse_conditions_compiles_regex_only(rules: ModuleType) -> None:
    """Verify regex_match conditions compile while string ops do not."""
    # Given a rule mixing a regex and a string operator
    conds = [
        {"field": "file_path", "operator": "regex_match", "pattern": r"\.env$"},
        {"field": "content", "operator": "contains", "pattern": "KEY"},
    ]
    data = {"rule": [_conditions_rule(conds)]}

    # When parsing
    parsed = rules.parse_rules(data, "rule", required=frozenset({"id", "level", "reason"}))

    # Then the regex condition is compiled and the string one is not
    rule = parsed[0]
    assert rule.regex is None
    assert rule.conditions[0].regex is not None
    assert rule.conditions[1].regex is None


@pytest.mark.parametrize(
    "bad",
    [
        pytest.param([], id="empty-list"),
        pytest.param([{"field": "f", "operator": "contains"}], id="missing-pattern"),
        pytest.param([{"field": "f", "operator": "nope", "pattern": "p"}], id="unknown-operator"),
        pytest.param(
            [{"field": "f", "operator": "contains", "pattern": "p", "x": "1"}],
            id="extra-field",
        ),
    ],
)
def test_parse_conditions_rejects_bad(rules: ModuleType, bad: list[dict[str, str]]) -> None:
    """Verify malformed condition lists raise."""
    # Given a conditions rule with a malformed list
    data = {"rule": [_conditions_rule(bad)]}

    # When/Then parsing raises
    with pytest.raises((ValueError, TypeError)):
        rules.parse_rules(data, "rule", required=frozenset({"id", "level", "reason"}))


# --- matching: single pattern ----------------------------------------------


def test_first_match_single_pattern_hits_text(rules: ModuleType) -> None:
    """Verify a single-pattern rule matches the primary text, not fields."""
    # Given a pattern rule
    data = {"rule": [_pattern_rule(pattern="token")]}
    parsed = rules.parse_rules(data, "rule", required=frozenset({"id", "level", "reason"}))

    # When the text contains the pattern
    hit = rules.first_match(parsed, text="my token here", threshold=rules.LEVELS["strict"])
    miss = rules.first_match(parsed, text="nothing", threshold=rules.LEVELS["strict"])

    # Then it matches the text and ignores absence in fields
    assert hit is not None
    assert miss is None


def test_field_qualified_pattern_matches_named_field(rules: ModuleType) -> None:
    """Verify a `field`-qualified pattern matches that field, not primary text."""
    # Given a pattern rule pinned to the `command` field
    data = {"rule": [_pattern_rule(pattern="boom", field="command")]}
    parsed = rules.parse_rules(data, "rule", required=frozenset({"id", "level", "reason"}))
    strict = rules.LEVELS["strict"]

    # When the named field holds the pattern (even if primary text does not)
    hit = rules.first_match(parsed, text="nothing", fields={"command": "boom!"}, threshold=strict)
    # And when only the primary text holds it (field set, so text is ignored)
    miss = rules.first_match(parsed, text="boom", fields={"command": "clean"}, threshold=strict)

    # Then it matches via the named field only
    assert hit is not None
    assert miss is None


def test_field_with_conditions_rejected(rules: ModuleType) -> None:
    """Verify combining `field` with `conditions` is a load error."""
    # Given a conditions rule that also sets a top-level field
    conds = [{"field": "f", "operator": "contains", "pattern": "x"}]
    data = {"rule": [_conditions_rule(conds, field="command")]}

    # When/Then parsing rejects it
    with pytest.raises(ValueError, match="field"):
        rules.parse_rules(data, "rule", required=frozenset({"id", "level", "reason"}))


# --- matching: operators ---------------------------------------------------


@pytest.mark.parametrize(
    ("operator", "pattern", "value", "expected"),
    [
        ("regex_match", r"\.env$", "app/.env", True),
        ("regex_match", r"\.env$", "app/env.txt", False),
        ("contains", "KEY", "API_KEY=1", True),
        ("contains", "KEY", "nope", False),
        ("not_contains", "KEY", "nope", True),
        ("not_contains", "KEY", "API_KEY=1", False),
        ("equals", "main", "main", True),
        ("equals", "main", "maintenance", False),
        ("starts_with", "src/", "src/app.py", True),
        ("starts_with", "src/", "lib/app.py", False),
        ("ends_with", ".py", "app.py", True),
        ("ends_with", ".py", "app.js", False),
        ("contains", "key", "API_KEY=1", True),  # case-insensitive
    ],
)
def test_condition_operators(
    rules: ModuleType,
    operator: str,
    pattern: str,
    value: str,
    expected: bool,  # noqa: FBT001
) -> None:
    """Verify each operator matches a single field as specified."""
    # Given a one-condition rule using the operator
    conds = [{"field": "f", "operator": operator, "pattern": pattern}]
    data = {"rule": [_conditions_rule(conds)]}
    parsed = rules.parse_rules(data, "rule", required=frozenset({"id", "level", "reason"}))

    # When matching against the field value
    hit = rules.first_match(parsed, fields={"f": value}, threshold=rules.LEVELS["strict"])

    # Then it matches iff expected
    assert (hit is not None) is expected


def test_conditions_are_anded(rules: ModuleType) -> None:
    """Verify a conditions rule fires only when every condition holds."""
    # Given a rule requiring a path suffix AND a content substring
    conds = [
        {"field": "file_path", "operator": "ends_with", "pattern": ".py"},
        {"field": "content", "operator": "contains", "pattern": "SECRET"},
    ]
    data = {"rule": [_conditions_rule(conds)]}
    parsed = rules.parse_rules(data, "rule", required=frozenset({"id", "level", "reason"}))
    strict = rules.LEVELS["strict"]

    # When only one condition holds vs both
    both = rules.first_match(
        parsed, fields={"file_path": "a.py", "content": "x SECRET y"}, threshold=strict
    )
    one = rules.first_match(
        parsed, fields={"file_path": "a.py", "content": "nothing"}, threshold=strict
    )

    # Then it fires only when both hold
    assert both is not None
    assert one is None


# --- matching: thresholds --------------------------------------------------


def test_threshold_skips_higher_level_rules(rules: ModuleType) -> None:
    """Verify a rule above the active threshold is skipped."""
    # Given a strict-level rule
    data = {"rule": [_pattern_rule(level="strict", pattern="x")]}
    parsed = rules.parse_rules(data, "rule", required=frozenset({"id", "level", "reason"}))

    # When the active threshold is only high
    at_high = rules.first_match(parsed, text="x", threshold=rules.LEVELS["high"])
    at_strict = rules.first_match(parsed, text="x", threshold=rules.LEVELS["strict"])

    # Then the strict rule fires only at the strict threshold
    assert at_high is None
    assert at_strict is not None


def test_no_threshold_treats_all_rules_eligible(rules: ModuleType) -> None:
    """Verify omitting a threshold matches regardless of level."""
    # Given a level-less rule (as stop_phrase_guard loads)
    data = {"violation": [{"reason": "stop", "pattern": "halt"}]}
    parsed = rules.parse_rules(data, "violation", required=frozenset({"reason"}))

    # When matching with no threshold
    hit = rules.first_match(parsed, text="please halt now")

    # Then it fires
    assert hit is not None


def test_first_match_is_first_wins(rules: ModuleType) -> None:
    """Verify the earliest matching rule in declaration order wins."""
    # Given two rules that both match
    data = {
        "rule": [
            _pattern_rule(id="first", pattern="a"),
            _pattern_rule(id="second", pattern="a"),
        ]
    }
    parsed = rules.parse_rules(data, "rule", required=frozenset({"id", "level", "reason"}))

    # When matching text both would hit
    hit = rules.first_match(parsed, text="a", threshold=rules.LEVELS["strict"])

    # Then the first declared rule is returned
    assert hit is not None
    assert hit.id == "first"


# --- allowlist parser ------------------------------------------------------


def test_parse_pattern_list_compiles(rules: ModuleType) -> None:
    """Verify a flat regex array compiles to patterns."""
    # Given an allowlist of two patterns
    data = {"allowlist": [r"\.env\.example$", r"sample"]}

    # When parsing the list
    compiled = rules.parse_pattern_list(data, "allowlist")

    # Then both compile and match as expected
    assert len(compiled) == 2
    assert compiled[0].search("app/.env.example")


@pytest.mark.parametrize(
    "data",
    [
        pytest.param({}, id="missing-key"),
        pytest.param({"allowlist": [1]}, id="non-string-entry"),
    ],
)
def test_parse_pattern_list_rejects_bad(rules: ModuleType, data: dict[str, Any]) -> None:
    """Verify a missing key or non-string entry raises TypeError."""
    # When/Then parsing raises TypeError
    with pytest.raises(TypeError):
        rules.parse_pattern_list(data, "allowlist")


# --- file round-trip -------------------------------------------------------


def test_load_rules_reads_toml_file(rules: ModuleType, tmp_path: Path) -> None:
    """Verify load_rules reads and parses a TOML file end to end."""
    # Given a TOML rules file on disk
    toml = tmp_path / "r.toml"
    toml.write_text(
        '[[rule]]\nid = "x"\nlevel = "high"\nreason = "r"\npattern = "boom"\n',
        encoding="utf-8",
    )

    # When loading it
    parsed = rules.load_rules(toml, "rule", required=frozenset({"id", "level", "reason"}))

    # Then the rule is available and matches
    assert rules.first_match(parsed, text="boom", threshold=rules.LEVELS["high"]) is not None
