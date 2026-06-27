"""File-based hook configuration with a global->project cascade.

# NOTE: not drift-guarded — different CONFIG_NAME (natelandau-recall.toml).

Resolution (low to high precedence): built-in defaults, then
~/.claude/natelandau-recall.toml, then $CLAUDE_PROJECT_DIR/.claude/
natelandau-recall.toml. Scalars and lists are replaced by the higher
level; [hooks.*] tables are deep-merged per key. Any read or parse error
is swallowed so a broken config never blocks tool execution.
"""

import os
import sys
import tomllib

# Mapping is referenced in a runtime-evaluated dataclass annotation, so it must
# stay a runtime import; TC003 would wrongly relocate it to a TYPE_CHECKING block.
from collections.abc import Mapping  # noqa: TC003
from dataclasses import dataclass, field
from pathlib import Path

VALID_PROFILES: frozenset[str] = frozenset({"minimal", "standard", "strict"})
DEFAULT_PROFILE = "standard"
CONFIG_NAME = "natelandau-recall.toml"


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

    def int_option(self, hook_id: str, key: str, default: int) -> int:
        """Return a per-hook integer option, falling back to default on absence/parse error."""
        raw = self.hook_options.get(hook_id, {}).get(key)
        if raw is None:
            return default
        try:
            return int(raw)
        except ValueError:
            return default


def _read_toml(path: Path) -> dict[str, object]:
    """Parse a TOML file, warning and returning {} on any failure."""
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except FileNotFoundError:
        return {}
    except (OSError, tomllib.TOMLDecodeError) as exc:
        print(f"natelandau-recall: ignoring {path}: {exc}", file=sys.stderr)  # noqa: T201
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


@dataclass
class _Accumulator:
    """Mutable config values folded across the global→project layers.

    A plain mutable holder so `_apply` overlays each layer in place; the
    final values are copied into the frozen `Config` once resolution and
    validation are done.
    """

    profile: str = DEFAULT_PROFILE
    disabled: frozenset[str] = frozenset()
    hook_options: dict[str, dict[str, str]] = field(default_factory=dict)


def _apply(layer: dict[str, object], acc: _Accumulator) -> None:
    """Overlay one config layer onto the accumulating values.

    A scalar or list key present in the layer replaces the accumulated
    value; `[hooks.*]` tables deep-merge per key. A key the layer omits
    leaves the accumulated value untouched, giving the low→high cascade.
    """
    raw_profile = layer.get("profile")
    if isinstance(raw_profile, str):
        acc.profile = raw_profile
    raw_disabled = layer.get("disabled_hooks")
    if isinstance(raw_disabled, list):
        acc.disabled = frozenset(x for x in raw_disabled if isinstance(x, str))
    _merge_hook_options(acc.hook_options, layer.get("hooks"))


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

    acc = _Accumulator()
    _apply(_read_toml(home / ".claude" / CONFIG_NAME), acc)
    if project_dir:
        proj_path = Path(project_dir) / ".claude" / CONFIG_NAME
        _apply(_read_toml(proj_path), acc)

    profile_is_valid = acc.profile in VALID_PROFILES
    resolved_profile = acc.profile if profile_is_valid else DEFAULT_PROFILE
    if not profile_is_valid:
        print(  # noqa: T201
            f"natelandau-recall: unknown profile {acc.profile!r}, using {DEFAULT_PROFILE}",
            file=sys.stderr,
        )
    return Config(
        profile=resolved_profile,
        disabled_hooks=acc.disabled,
        hook_options={k: dict(v) for k, v in acc.hook_options.items()},
        project_dir=project_dir,
    )
