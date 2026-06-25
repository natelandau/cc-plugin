"""Manifest and component-wiring validation.

Catches install-time failures the per-hook unit tests can't see:
unresolved ${CLAUDE_PLUGIN_ROOT}/... references, orphan hook scripts,
SKILL.md and command files missing required frontmatter. Per-component
behavior coverage stays in the dedicated test modules.
"""

from __future__ import annotations

import ast
import json
import os
import re
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent / "plugins" / "natelandau-toolkit"
PLUGIN_ROOT_PREFIX = "${CLAUDE_PLUGIN_ROOT}/"

# Documented in CLAUDE.md: transfer-context.md predates the frontmatter
# convention and works via filename fallback. New commands must include it.
COMMANDS_WITHOUT_FRONTMATTER = frozenset({"transfer-context.md"})

# Per-stage dispatcher scripts that exist but are not yet wired into hooks.json.
# Each will replace the legacy wiring for its event in a later task; listing them
# here exempts them from the orphan guard until that cutover lands. PreToolUse
# (pretooluse.py) is already wired, so it is intentionally absent. Stop currently
# runs the flat stop_phrase_guard.py / capture_followups.py scripts, so stop.py
# stays exempt until Task 6 cuts it over.
STAGE_DISPATCHERS = frozenset(
    {
        "posttooluse.py",
        "stop.py",
        "sessionstart.py",
        "sessionend.py",
    }
)

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _parse_frontmatter(text: str) -> dict[str, str] | None:
    """Extract top-level key/value pairs from a YAML frontmatter block.

    Intentionally minimal: handles the flat `key: value` shape every component
    in this plugin uses, plus indented continuation lines (the `documentation-writer`
    skill folds its description across two lines). Avoids a PyYAML dep so the
    test suite stays as light as the hook scripts themselves.
    """
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return None
    fields: dict[str, str] = {}
    current_key: str | None = None
    for line in match.group(1).splitlines():
        if not line.strip():
            continue
        # Indented continuation appends to the previous key's value.
        if line[:1].isspace() and current_key is not None:
            fields[current_key] = f"{fields[current_key]} {line.strip()}"
            continue
        if ":" in line:
            key, _, value = line.partition(":")
            current_key = key.strip()
            fields[current_key] = value.strip()
    return fields


def _hook_commands() -> list[tuple[str, str]]:
    """Return (event, command) for every command-type hook in hooks.json."""
    data = json.loads((PLUGIN_ROOT / "hooks" / "hooks.json").read_text())
    out: list[tuple[str, str]] = []
    for event, entries in data.get("hooks", {}).items():
        for entry in entries:
            for hook in entry.get("hooks", []):
                if hook.get("type") == "command":
                    out.append((event, hook["command"]))
    return out


def _registered_hook_paths() -> set[Path]:
    """Resolve every hooks.json command back to its absolute script path."""
    paths: set[Path] = set()
    for _event, command in _hook_commands():
        if command.startswith(PLUGIN_ROOT_PREFIX):
            paths.add(PLUGIN_ROOT / command[len(PLUGIN_ROOT_PREFIX) :])
    return paths


def _skill_files() -> list[Path]:
    return sorted((PLUGIN_ROOT / "skills").glob("*/SKILL.md"))


def _command_files() -> list[Path]:
    return sorted((PLUGIN_ROOT / "commands").glob("*.md"))


def _hook_scripts() -> list[Path]:
    return sorted((PLUGIN_ROOT / "hooks").glob("*.py"))


# Filenames inside a stage dir that are package scaffolding, not plugin modules.
_STAGE_NON_PLUGIN = frozenset({"_registry.py", "__init__.py"})


def _stage_dirs() -> list[Path]:
    """Return every per-stage plugin directory (one holding a _registry.py)."""
    return sorted(p.parent for p in (PLUGIN_ROOT / "hooks").glob("*/_registry.py"))


def _stage_plugin_modules(stage_dir: Path) -> list[Path]:
    """Return a stage's plugin module files (its *.py minus scaffolding)."""
    return sorted(p for p in stage_dir.glob("*.py") if p.name not in _STAGE_NON_PLUGIN)


def _registered_plugin_names(stage_dir: Path) -> set[str]:
    """Parse a stage's _registry.py and return the module names in PLUGINS.

    Reads the AST rather than importing so the guard does not depend on the
    hooks dir being importable. PLUGINS is a list of (module_name, profiles)
    tuples; only the first element of each tuple is the module name.
    """
    tree = ast.parse((stage_dir / "_registry.py").read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        # PLUGINS may be a bare or annotated assignment (`PLUGINS: list[...] = [...]`).
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        if not isinstance(node.value, ast.List):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "PLUGINS" for t in targets):
            continue
        for elt in node.value.elts:
            if isinstance(elt, ast.Tuple) and elt.elts:
                first = elt.elts[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    names.add(first.value)
    return names


def _stage_plugin_params() -> list[tuple[Path, str]]:
    """Flatten (stage_dir, plugin.py) pairs across every stage for parametrize."""
    return [(d, m.name) for d in _stage_dirs() for m in _stage_plugin_modules(d)]


def _agent_files() -> list[Path]:
    return sorted((PLUGIN_ROOT / "agents").glob("*.md"))


def test_plugin_manifest_has_required_fields() -> None:
    """Verify .claude-plugin/plugin.json parses with name and description."""
    # Given the plugin manifest
    manifest_path = PLUGIN_ROOT / ".claude-plugin" / "plugin.json"

    # When parsed
    data = json.loads(manifest_path.read_text())

    # Then required top-level fields are present
    assert "name" in data, "plugin.json missing 'name'"
    assert "description" in data, "plugin.json missing 'description'"


def test_hooks_json_parses() -> None:
    """Verify hooks/hooks.json parses and declares at least one event."""
    # Given the hooks manifest
    data = json.loads((PLUGIN_ROOT / "hooks" / "hooks.json").read_text())

    # Then it contains a non-empty hooks block
    assert isinstance(data.get("hooks"), dict)
    assert data["hooks"], "hooks.json declares no events"


@pytest.mark.parametrize(
    ("event", "command"),
    _hook_commands(),
    ids=lambda v: v if isinstance(v, str) else "",
)
def test_hooks_json_command_resolves(event: str, command: str) -> None:
    """Verify each hooks.json command points at an executable script."""
    # Given a registered hook command
    assert command.startswith(PLUGIN_ROOT_PREFIX), (
        f"{event}: command must start with {PLUGIN_ROOT_PREFIX}, got {command!r}"
    )

    # When resolved against the plugin root
    resolved = PLUGIN_ROOT / command[len(PLUGIN_ROOT_PREFIX) :]

    # Then the file exists and the executable bit is set
    assert resolved.is_file(), f"{event}: missing file {resolved}"
    assert os.access(resolved, os.X_OK), f"{event}: not executable {resolved}"


@pytest.mark.parametrize("script_path", _hook_scripts(), ids=lambda p: p.name)
def test_hook_script_is_registered(script_path: Path) -> None:
    """Verify every hooks/*.py root script is wired into hooks.json or awaiting cutover.

    Catches the easy mistake of dropping a new hook script in place but
    forgetting the manifest entry, which leaves it dead on disk. Plugin modules
    no longer live at the hooks root (they sit under hooks/<stage>/ and are
    reached via that stage's _registry.py, covered by
    test_stage_plugin_is_registered); only dispatcher entry points and the flat
    Stop hooks live here.
    """
    # Given the set of scripts referenced from hooks.json
    registered = _registered_hook_paths()

    # Then this script is either registered directly in hooks.json or is a stage
    # dispatcher awaiting hooks.json cutover. A script that is neither is a real
    # orphan and must fail.
    assert script_path in registered or script_path.name in STAGE_DISPATCHERS, (
        f"{script_path.name} exists in hooks/ but is not registered in hooks.json "
        f"and is not listed in STAGE_DISPATCHERS"
    )


@pytest.mark.parametrize(
    ("stage_dir", "module_name"),
    _stage_plugin_params(),
    ids=lambda v: v if isinstance(v, str) else "",
)
def test_stage_plugin_is_registered(stage_dir: Path, module_name: str) -> None:
    """Verify every plugin module under a stage dir is listed in its _registry.py.

    A plugin module that the dispatcher never loads (absent from PLUGINS) is
    dead on disk just like an unwired root script. The module name in PLUGINS
    is the file stem, so a `protect_secrets.py` must appear as `protect_secrets`.
    """
    # Given the module names the stage's registry will load
    registered = _registered_plugin_names(stage_dir)

    # Then this plugin module's stem appears in PLUGINS
    stem = module_name.removesuffix(".py")
    assert stem in registered, (
        f"{stage_dir.name}/{module_name} is not listed in {stage_dir.name}/_registry.py "
        f"PLUGINS, so the dispatcher would never load it"
    )


@pytest.mark.parametrize("skill_path", _skill_files(), ids=lambda p: p.parent.name)
def test_skill_has_required_frontmatter(skill_path: Path) -> None:
    """Verify every SKILL.md declares name and description in frontmatter."""
    # Given a skill entry file
    fields = _parse_frontmatter(skill_path.read_text())

    # Then frontmatter parses with both required fields
    assert fields is not None, f"{skill_path}: missing YAML frontmatter"
    assert "name" in fields, f"{skill_path}: frontmatter missing 'name'"
    assert "description" in fields, f"{skill_path}: frontmatter missing 'description'"


@pytest.mark.parametrize("skill_path", _skill_files(), ids=lambda p: p.parent.name)
def test_skill_name_matches_directory(skill_path: Path) -> None:
    """Verify SKILL.md frontmatter 'name' equals the containing directory."""
    # Given a skill entry file
    fields = _parse_frontmatter(skill_path.read_text())
    assert fields is not None  # covered by the frontmatter test

    # Then frontmatter name aligns with the on-disk slug used by the router
    assert fields.get("name") == skill_path.parent.name, (
        f"{skill_path}: frontmatter name {fields.get('name')!r} "
        f"!= directory {skill_path.parent.name!r}"
    )


@pytest.mark.parametrize("command_path", _command_files(), ids=lambda p: p.name)
def test_command_has_frontmatter(command_path: Path) -> None:
    """Verify every commands/*.md declares description frontmatter."""
    # Given a command file (with documented exemptions skipped)
    if command_path.name in COMMANDS_WITHOUT_FRONTMATTER:
        pytest.skip(f"{command_path.name}: documented frontmatter exemption")

    # When the frontmatter is parsed
    fields = _parse_frontmatter(command_path.read_text())

    # Then it exists and contains a description
    assert fields is not None, f"{command_path}: missing YAML frontmatter"
    assert "description" in fields, f"{command_path}: frontmatter missing 'description'"


@pytest.mark.parametrize("agent_path", _agent_files(), ids=lambda p: p.stem)
def test_agent_has_required_frontmatter(agent_path: Path) -> None:
    """Verify every agents/*.md declares name and description in frontmatter."""
    # Given a subagent definition
    fields = _parse_frontmatter(agent_path.read_text())

    # Then frontmatter parses with both required fields
    assert fields is not None, f"{agent_path}: missing YAML frontmatter"
    assert "name" in fields, f"{agent_path}: frontmatter missing 'name'"
    assert "description" in fields, f"{agent_path}: frontmatter missing 'description'"


@pytest.mark.parametrize("agent_path", _agent_files(), ids=lambda p: p.stem)
def test_agent_name_matches_filename(agent_path: Path) -> None:
    """Verify agents/*.md frontmatter 'name' equals the file stem used to dispatch it."""
    # Given a subagent definition
    fields = _parse_frontmatter(agent_path.read_text())
    assert fields is not None  # covered by the frontmatter test

    # Then frontmatter name aligns with the on-disk slug
    assert fields.get("name") == agent_path.stem, (
        f"{agent_path}: frontmatter name {fields.get('name')!r} != file stem {agent_path.stem!r}"
    )
