"""Unit tests for the commit-message hook's imperative-verb lexicon."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests._helpers import load_hook_module

if TYPE_CHECKING:
    from pathlib import Path
    from types import ModuleType

# Regression corpus: non-imperative forms and the base verb each must suggest.
LEGACY_FORMS = [
    "added:add",
    "adding:add",
    "adds:add",
    "allowed:allow",
    "allowing:allow",
    "allows:allow",
    "amended:amend",
    "amending:amend",
    "amends:amend",
    "appended:append",
    "appending:append",
    "appends:append",
    "applied:apply",
    "applies:apply",
    "applying:apply",
    "batched:batch",
    "batches:batch",
    "batching:batch",
    "blocked:block",
    "blocking:block",
    "blocks:block",
    "building:build",
    "builds:build",
    "built:build",
    "bumped:bump",
    "bumping:bump",
    "bumps:bump",
    "changed:change",
    "changes:change",
    "changing:change",
    "cleaned:clean",
    "cleaning:clean",
    "cleans:clean",
    "commits:commit",
    "committing:commit",
    "consolidated:consolidate",
    "consolidates:consolidate",
    "consolidating:consolidate",
    "converted:convert",
    "converting:convert",
    "converts:convert",
    "copied:copy",
    "copies:copy",
    "copying:copy",
    "corrected:correct",
    "correcting:correct",
    "corrects:correct",
    "created:create",
    "creates:create",
    "creating:create",
    "decreased:decrease",
    "decreases:decrease",
    "decreasing:decrease",
    "deduped:dedupe",
    "dedupes:dedupe",
    "deduping:dedupe",
    "deferred:defer",
    "deferring:defer",
    "defers:defer",
    "deleted:delete",
    "deletes:delete",
    "deleting:delete",
    "deprecated:deprecate",
    "deprecates:deprecate",
    "deprecating:deprecate",
    "documented:document",
    "documenting:document",
    "documents:document",
    "dropped:drop",
    "dropping:drop",
    "drops:drop",
    "enforced:enforce",
    "enforces:enforce",
    "enforcing:enforce",
    "enhanced:enhance",
    "enhances:enhance",
    "enhancing:enhance",
    "expanded:expand",
    "expanding:expand",
    "expands:expand",
    "exposed:expose",
    "exposes:expose",
    "exposing:expose",
    "extracted:extract",
    "extracting:extract",
    "extracts:extract",
    "fixed:fix",
    "fixes:fix",
    "fixing:fix",
    "gated:gate",
    "gates:gate",
    "gathered:gather",
    "gathering:gather",
    "gathers:gather",
    "gating:gate",
    "generated:generate",
    "generates:generate",
    "generating:generate",
    "gives:give",
    "grouped:group",
    "grouping:group",
    "groups:group",
    "implemented:implement",
    "implementing:implement",
    "implements:implement",
    "improved:improve",
    "improves:improve",
    "improving:improve",
    "increased:increase",
    "increases:increase",
    "increasing:increase",
    "initialized:initialize",
    "initializes:initialize",
    "initializing:initialize",
    "injected:inject",
    "injecting:inject",
    "injects:inject",
    "introduced:introduce",
    "introduces:introduce",
    "introducing:introduce",
    "keeping:keep",
    "keeps:keep",
    "kept:keep",
    "laid:lay",
    "laying:lay",
    "lays:lay",
    "made:make",
    "makes:make",
    "making:make",
    "merged:merge",
    "merges:merge",
    "merging:merge",
    "migrated:migrate",
    "migrates:migrate",
    "migrating:migrate",
    "moved:move",
    "moves:move",
    "moving:move",
    "optimized:optimize",
    "optimizes:optimize",
    "optimizing:optimize",
    "passed:pass",
    "passes:pass",
    "passing:pass",
    "ported:port",
    "porting:port",
    "ports:port",
    "redesigned:redesign",
    "redesigning:redesign",
    "redesigns:redesign",
    "refactored:refactor",
    "refactoring:refactor",
    "refactors:refactor",
    "removed:remove",
    "removes:remove",
    "removing:remove",
    "renamed:rename",
    "renames:rename",
    "renaming:rename",
    "rendered:render",
    "rendering:render",
    "renders:render",
    "replaced:replace",
    "replaces:replace",
    "replacing:replace",
    "resolves:resolve",
    "resolving:resolve",
    "restored:restore",
    "restores:restore",
    "restoring:restore",
    "restructured:restructure",
    "restructures:restructure",
    "restructuring:restructure",
    "reverted:revert",
    "reverting:revert",
    "reverts:revert",
    "scrubbed:scrub",
    "scrubbing:scrub",
    "scrubs:scrub",
    "sets:set",
    "setting:set",
    "showing:show",
    "shows:show",
    "simplified:simplify",
    "simplifies:simplify",
    "simplifying:simplify",
    "sorted:sort",
    "sorting:sort",
    "sorts:sort",
    "squashed:squash",
    "squashes:squash",
    "squashing:squash",
    "stripped:strip",
    "stripping:strip",
    "strips:strip",
    "supported:support",
    "supporting:support",
    "supports:support",
    "switched:switch",
    "switches:switch",
    "switching:switch",
    "tightened:tighten",
    "tightens:tighten",
    "tweaked:tweak",
    "tweaking:tweak",
    "tweaks:tweak",
    "updated:update",
    "updates:update",
    "updating:update",
    "used:use",
    "uses:use",
    "using:use",
    "verified:verify",
    "verifies:verify",
    "verifying:verify",
    "wired:wire",
    "wires:wire",
    "wiring:wire",
]


@pytest.fixture(scope="module")
def hook(hooks_dir: Path) -> ModuleType:
    """Load the commit-message hook module in-process."""
    return load_hook_module(
        hooks_dir, "pretooluse/enforce_commit_message.py", "_commit_message_under_test"
    )


@pytest.mark.parametrize("pair", LEGACY_FORMS)
def test_verb_lexicon_blocks_legacy_forms(hook: ModuleType, pair: str) -> None:
    """Verify the shipped verb file blocks every legacy form with the same suggestion."""
    form, base = pair.split(":")
    assert hook.verb_lexicon().suggest(form) == base


@pytest.mark.parametrize(
    "word",
    [
        # Base verbs, including ones that end like an inflection.
        "add",
        "pass",
        "release",
        "address",
        "feed",
        "read",
        # Unlisted words that a bare suffix rule would misread.
        "ring",
        "layer",
        "bring",
        "string",
        "during",
        "status",
        "need",
    ],
)
def test_verb_lexicon_allows_imperatives_and_unknown_words(hook: ModuleType, word: str) -> None:
    """Verify base verbs, unlisted words, and allowed nouns are never blocked."""
    assert hook.verb_lexicon().suggest(word) is None


@pytest.mark.parametrize(
    ("word", "base"),
    [
        ("applies", "apply"),
        ("copied", "copy"),
        ("fixes", "fix"),
        ("runs", "run"),
        ("moved", "move"),
        ("moving", "move"),
        ("dropped", "drop"),
        ("running", "run"),
        ("Added", "add"),
        ("wrote", "write"),
        # -ing words that read as nouns still take the base verb.
        ("linting", "lint"),
        ("scaffolding", "scaffold"),
        ("logging", "log"),
        ("mapping", "map"),
    ],
)
def test_verb_lexicon_reverses_each_inflection_rule(hook: ModuleType, word: str, base: str) -> None:
    """Verify each suffix rule and the irregular map recover the base verb."""
    assert hook.verb_lexicon().suggest(word) == base


def test_verb_lexicon_parses_every_line_form(hook: ModuleType) -> None:
    """Verify comments, verbs, `!word` exceptions, and `form -> verb` lines all parse."""
    # Given a verb file using every line form
    text = "# header\nring  # trailing comment\n\n!rings\n-user\nrang -> ring\nSing\n"

    # When parsing it
    lexicon = hook.VerbLexicon.parse(text)

    # Then each form lands in its own table, lowercased
    assert lexicon.verbs == frozenset({"ring", "sing"})
    assert lexicon.allowed == frozenset({"rings"})
    assert lexicon.denied == frozenset({"user"})
    assert lexicon.is_denied("User")
    assert dict(lexicon.irregular) == {"rang": "ring"}
    assert lexicon.suggest("rings") is None
    assert lexicon.suggest("rang") == "ring"
    assert lexicon.suggest("singing") == "sing"


def test_verb_lexicon_unreadable_file_disables_rule(
    hook: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify a missing verb file yields an empty lexicon instead of raising."""
    # Given the verb file path points at nothing
    monkeypatch.setattr(hook, "VERBS_FILE", tmp_path / "missing.txt")
    hook.verb_lexicon.cache_clear()

    try:
        # When loading the lexicon
        lexicon = hook.verb_lexicon()

        # Then nothing is blocked
        assert lexicon.suggest("added") is None
    finally:
        hook.verb_lexicon.cache_clear()


@pytest.mark.parametrize("word", ["user", "admin", "initial", "single", "first"])
def test_verb_lexicon_denies_listed_non_verbs(hook: ModuleType, word: str) -> None:
    """Verify the shipped verb file denies the non-verbs subjects commonly open with."""
    assert hook.verb_lexicon().is_denied(word)
