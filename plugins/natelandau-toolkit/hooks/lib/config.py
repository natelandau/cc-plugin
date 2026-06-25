# plugins/natelandau-toolkit/hooks/lib/config.py
"""File-based hook configuration with a global->project cascade.

Resolution (low to high precedence): built-in defaults, then
~/.claude/natelandau-toolkit.toml, then $CLAUDE_PROJECT_DIR/.claude/
natelandau-toolkit.toml. Scalars and lists are replaced by the higher
level; [hooks.*] tables are deep-merged per key. Any read or parse error
is swallowed so a broken config never blocks tool execution.
"""

import os
import sys
import tomllib

# Mapping is referenced in a runtime-evaluated dataclass annotation, so it must
# stay a runtime import; TC003 would wrongly relocate it to a TYPE_CHECKING block.
from collections.abc import Mapping  # noqa: TC003
from dataclasses import dataclass
from pathlib import Path

VALID_PROFILES: frozenset[str] = frozenset({"minimal", "standard", "strict"})
DEFAULT_PROFILE = "standard"
CONFIG_NAME = "natelandau-toolkit.toml"


@dataclass(frozen=True, slots=True)
class Config:
    """Resolved hook configuration."""

    profile: str
    disabled_hooks: frozenset[str]
    hook_options: Mapping[str, Mapping[str, str]]
    project_dir: str | None = None

    def option(self, hook_id: str, key: str, default: str) -> str:
        """Return a per-hook option value, or `default` when unset."""
        return self.hook_options.get(hook_id, {}).get(key, default)


def _read_toml(path: Path) -> dict[str, object]:
    """Parse a TOML file, warning and returning {} on any failure."""
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except FileNotFoundError:
        return {}
    except (OSError, tomllib.TOMLDecodeError) as exc:
        print(f"natelandau-toolkit: ignoring {path}: {exc}", file=sys.stderr)  # noqa: T201
        return {}


def _merge_hook_options(base: dict[str, dict[str, str]], raw: object) -> dict[str, dict[str, str]]:
    """Deep-merge a [hooks.*] table of string options per hook id."""
    if not isinstance(raw, dict):
        return base
    for hook_id, table in raw.items():
        if not isinstance(hook_id, str) or not isinstance(table, dict):
            continue
        base[hook_id] = {
            **base.get(hook_id, {}),
            **{
                key: value
                for key, value in table.items()
                if isinstance(key, str) and isinstance(value, str)
            },
        }
    return base


def _apply(
    layer: dict[str, object],
    profile: list[str],
    disabled: list[frozenset[str]],
    hook_options: dict[str, dict[str, str]],
) -> None:
    """Overlay one config layer onto the accumulating values."""
    raw_profile = layer.get("profile")
    if isinstance(raw_profile, str):
        profile[0] = raw_profile
    raw_disabled = layer.get("disabled_hooks")
    if isinstance(raw_disabled, list):
        disabled[0] = frozenset(x for x in raw_disabled if isinstance(x, str))
    _merge_hook_options(hook_options, layer.get("hooks"))


def load_config(*, home: Path | None = None, project_dir: str | None = None) -> Config:
    """Load and merge global then project config, never raising.

    Args:
        home: Override for the user home directory (tests). Defaults to
            Path.home().
        project_dir: Override for the project root (tests). Defaults to
            the CLAUDE_PROJECT_DIR environment variable.
    """
    home = home or Path.home()
    project_dir = project_dir if project_dir is not None else os.environ.get("CLAUDE_PROJECT_DIR")

    profile: list[str] = [DEFAULT_PROFILE]
    disabled: list[frozenset[str]] = [frozenset()]
    hook_options: dict[str, dict[str, str]] = {}

    _apply(_read_toml(home / ".claude" / CONFIG_NAME), profile, disabled, hook_options)
    if project_dir:
        proj_path = Path(project_dir) / ".claude" / CONFIG_NAME
        _apply(_read_toml(proj_path), profile, disabled, hook_options)

    resolved_profile = profile[0] if profile[0] in VALID_PROFILES else DEFAULT_PROFILE
    # DEFAULT_PROFILE is itself a member of VALID_PROFILES, so an out-of-set
    # value can never equal it; the membership test alone gates the warning.
    if profile[0] not in VALID_PROFILES:
        print(  # noqa: T201
            f"natelandau-toolkit: unknown profile {profile[0]!r}, using {DEFAULT_PROFILE}",
            file=sys.stderr,
        )
    return Config(
        profile=resolved_profile,
        disabled_hooks=disabled[0],
        hook_options={k: dict(v) for k, v in hook_options.items()},
        project_dir=project_dir,
    )
