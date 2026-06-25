"""Unit tests for hooks/lib/rules.py: the shared loader and matcher.

Exercises parsing/validation of both rule forms (single or list `pattern`
and multi-field `conditions`), every condition operator, first-match-wins
ordering, and the flat allowlist parser. Rules are built by passing plain
dicts straight to `parse_rules`, so the parser is covered alongside the matcher.
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
    return {"id": "r1", "reason": "because", "pattern": "secret", **over}


def _conditions_rule(conditions: list[dict[str, str]], **over: Any) -> dict[str, Any]:
    """Build a conditions rule table with the given condition list."""
    return {"id": "c1", "reason": "because", "conditions": conditions, **over}


# --- parsing: single-pattern form ------------------------------------------


def test_parse_rules_single_pattern(rules: ModuleType) -> None:
    """Verify a single-pattern rule parses into a compiled regex Rule."""
    # Given one valid pattern rule
    data = {"rule": [_pattern_rule()]}

    # When parsing the section
    parsed = rules.parse_rules(data, "rule", required=frozenset({"id", "reason"}))

    # Then one Rule with a single compiled pattern and no conditions is returned
    assert len(parsed) == 1
    assert parsed[0].id == "r1"
    assert len(parsed[0].patterns) == 1
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
        pytest.param({"id": "x", "reason": "r"}, ValueError, id="no-matcher"),
        pytest.param(
            {"id": "x", "reason": "r", "pattern": "p", "conditions": []},
            ValueError,
            id="two-matchers",
        ),
        pytest.param({"reason": "r", "pattern": "p"}, ValueError, id="missing-id"),
        pytest.param(
            {"id": "x", "reason": "r", "pattern": "p", "extra": "1"},
            ValueError,
            id="unknown-field",
        ),
        pytest.param(
            {"id": 5, "reason": "r", "pattern": "p"},
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
        rules.parse_rules(data, "rule", required=frozenset({"id", "reason"}))


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
    parsed = rules.parse_rules(data, "rule", required=frozenset({"id", "reason"}))

    # Then the regex condition is compiled and the string one is not
    rule = parsed[0]
    assert rule.patterns == ()
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
        rules.parse_rules(data, "rule", required=frozenset({"id", "reason"}))


# --- matching: single pattern ----------------------------------------------


def test_first_match_single_pattern_hits_text(rules: ModuleType) -> None:
    """Verify a single-pattern rule matches the primary text, not fields."""
    # Given a pattern rule
    data = {"rule": [_pattern_rule(pattern="token")]}
    parsed = rules.parse_rules(data, "rule", required=frozenset({"id", "reason"}))

    # When the text contains the pattern
    hit = rules.first_match(parsed, text="my token here")
    miss = rules.first_match(parsed, text="nothing")

    # Then it matches the text and ignores absence in fields
    assert hit is not None
    assert miss is None


def test_list_pattern_or_combines(rules: ModuleType) -> None:
    """Verify a list `pattern` matches if any of its patterns matches."""
    # Given one rule whose pattern is a list of alternatives
    data = {"rule": [_pattern_rule(pattern=["alpha", "bravo", "charlie"])]}
    parsed = rules.parse_rules(data, "rule", required=frozenset({"id", "reason"}))

    # Then all three patterns compile under the one rule
    assert len(parsed[0].patterns) == 3

    # And the rule fires for any alternative and misses when none is present
    assert rules.first_match(parsed, text="contains bravo here") is not None
    assert rules.first_match(parsed, text="contains charlie") is not None
    assert rules.first_match(parsed, text="none of them") is None


@pytest.mark.parametrize(
    ("pattern", "exc"),
    [
        pytest.param([], ValueError, id="empty-list"),
        pytest.param(["ok", 5], TypeError, id="non-string-item"),
    ],
)
def test_list_pattern_rejects_bad(rules: ModuleType, pattern: object, exc: type[Exception]) -> None:
    """Verify an empty or non-string list pattern raises at load time."""
    # Given a rule with a malformed list pattern
    data = {"rule": [_pattern_rule(pattern=pattern)]}

    # When/Then parsing raises the expected error type
    with pytest.raises(exc):
        rules.parse_rules(data, "rule", required=frozenset({"id", "reason"}))


def test_field_qualified_pattern_matches_named_field(rules: ModuleType) -> None:
    """Verify a `field`-qualified pattern matches that field, not primary text."""
    # Given a pattern rule pinned to the `command` field
    data = {"rule": [_pattern_rule(pattern="boom", field="command")]}
    parsed = rules.parse_rules(data, "rule", required=frozenset({"id", "reason"}))

    # When the named field holds the pattern (even if primary text does not)
    hit = rules.first_match(parsed, text="nothing", fields={"command": "boom!"})
    # And when only the primary text holds it (field set, so text is ignored)
    miss = rules.first_match(parsed, text="boom", fields={"command": "clean"})

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
        rules.parse_rules(data, "rule", required=frozenset({"id", "reason"}))


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
    parsed = rules.parse_rules(data, "rule", required=frozenset({"id", "reason"}))

    # When matching against the field value
    hit = rules.first_match(parsed, fields={"f": value})

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
    parsed = rules.parse_rules(data, "rule", required=frozenset({"id", "reason"}))

    # When only one condition holds vs both
    both = rules.first_match(parsed, fields={"file_path": "a.py", "content": "x SECRET y"})
    one = rules.first_match(parsed, fields={"file_path": "a.py", "content": "nothing"})

    # Then it fires only when both hold
    assert both is not None
    assert one is None


# --- matching: declaration order -------------------------------------------


def test_first_match_idless_rule(rules: ModuleType) -> None:
    """Verify a rule carrying only reason+pattern matches (no id)."""
    # Given an id-less rule (as stop_phrase_guard loads)
    data = {"violation": [{"reason": "stop", "pattern": "halt"}]}
    parsed = rules.parse_rules(data, "violation", required=frozenset({"reason"}))

    # When matching text that holds the pattern
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
    parsed = rules.parse_rules(data, "rule", required=frozenset({"id", "reason"}))

    # When matching text both would hit
    hit = rules.first_match(parsed, text="a")

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
        '[[rule]]\nid = "x"\nreason = "r"\npattern = "boom"\n',
        encoding="utf-8",
    )

    # When loading it
    parsed = rules.load_rules(toml, "rule", required=frozenset({"id", "reason"}))

    # Then the rule is available and matches
    assert rules.first_match(parsed, text="boom") is not None


# --- per-project additive rules --------------------------------------------

_PROJECT_RULE_TOML = """\
[[rule]]
id = "proj-block"
reason = "project specific block"
pattern = "topsecret"
"""


def _project_file(tmp_path: Path, filename: str, content: str) -> str:
    """Write a project rules file and return the project dir as a string."""
    d = tmp_path / ".claude" / "natelandau-toolkit"
    d.mkdir(parents=True, exist_ok=True)
    (d / filename).write_text(content, encoding="utf-8")
    return str(tmp_path)


def test_project_rules_path_none_without_project_dir(rules: ModuleType) -> None:
    """Verify path resolution returns None when no project dir is given."""
    # Given no project dir
    # When resolving a project rules path
    result = rules.project_rules_path("x.rules.toml", project_dir=None)
    # Then nothing is resolved
    assert result is None


def test_project_rules_path_none_when_file_absent(rules: ModuleType, tmp_path: Path) -> None:
    """Verify path resolution returns None when the project file is missing."""
    # Given a project dir with no rules file
    # When resolving the path
    result = rules.project_rules_path("x.rules.toml", project_dir=str(tmp_path))
    # Then nothing is resolved
    assert result is None


def test_project_rules_path_resolves_existing_file(rules: ModuleType, tmp_path: Path) -> None:
    """Verify path resolution returns the file when it exists under the project dir."""
    # Given a project rules file on disk
    proj = _project_file(tmp_path, "x.rules.toml", _PROJECT_RULE_TOML)
    # When resolving the path
    result = rules.project_rules_path("x.rules.toml", project_dir=proj)
    # Then the resolved path points at the project file
    assert result is not None
    assert result.name == "x.rules.toml"
    assert result.exists()


def test_load_project_rules_empty_without_file(rules: ModuleType, tmp_path: Path) -> None:
    """Verify loading returns an empty tuple when no project file exists."""
    # Given a project dir with no rules file
    # When loading project rules
    result = rules.load_project_rules(
        "x.rules.toml",
        "rule",
        required=frozenset({"id", "reason"}),
        project_dir=str(tmp_path),
    )
    # Then nothing is loaded
    assert result == ()


def test_load_project_rules_parses_present_file(rules: ModuleType, tmp_path: Path) -> None:
    """Verify a present, valid project file parses into Rules."""
    # Given a valid project rules file
    proj = _project_file(tmp_path, "x.rules.toml", _PROJECT_RULE_TOML)
    # When loading project rules
    result = rules.load_project_rules(
        "x.rules.toml", "rule", required=frozenset({"id", "reason"}), project_dir=proj
    )
    # Then the project rule is returned
    assert len(result) == 1
    assert result[0].id == "proj-block"


def test_load_project_rules_fails_open_on_malformed(
    rules: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Verify a malformed project file is ignored with a stderr warning."""
    # Given a malformed project rules file
    proj = _project_file(tmp_path, "x.rules.toml", "this is = = not toml\n")
    # When loading project rules
    result = rules.load_project_rules(
        "x.rules.toml", "rule", required=frozenset({"id", "reason"}), project_dir=proj
    )
    # Then nothing is loaded and a warning is emitted
    assert result == ()
    assert "ignoring project rules" in capsys.readouterr().err
