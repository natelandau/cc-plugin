"""Flat, file-based recall configuration with a global->project cascade.

Resolution (low to high precedence): built-in defaults, then
~/.claude/natelandau-recall.toml, then $CLAUDE_PROJECT_DIR/.claude/
natelandau-recall.toml (project wins per key). The schema is two flat tables,
`[inject]` and `[sweep]`; there are no profiles or per-hook disable lists. Any
read or parse error is swallowed (warned to stderr) so a broken config never
wedges a session.
"""

from __future__ import annotations

import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

CONFIG_NAME = "natelandau-recall.toml"

DEFAULT_ARCHITECTURE_MAX_BYTES = 4096
DEFAULT_SWEEP_MODEL = "claude-sonnet-4-6"
# Counts individual meaningful messages (user + assistant), not paired turns,
# so this is ~5 back-and-forth turns — a floor that keeps trivial sessions
# (a quick question, a one-line fix) from triggering a sweep at all.
DEFAULT_MIN_EXCHANGES = 10


@dataclass(frozen=True, slots=True)
class RecallConfig:
    """Resolved recall settings (flat; one toggle per hook)."""

    inject_enabled: bool = True
    architecture_max_bytes: int = DEFAULT_ARCHITECTURE_MAX_BYTES
    sweep_enabled: bool = True
    sweep_model: str = DEFAULT_SWEEP_MODEL
    min_exchanges: int = DEFAULT_MIN_EXCHANGES

    @classmethod
    def load(cls, *, home: Path | None = None, project_dir: str | None = None) -> RecallConfig:
        """Load and merge global then project config, never raising.

        Args:
            home: Override for the user home directory (tests). Defaults to
                Path.home().
            project_dir: The project root whose `.claude/` may override the
                global file; pass the CLAUDE_PROJECT_DIR value (or None to skip).
        """
        home = home or Path.home()
        merged: dict[str, dict[str, object]] = {}
        _overlay(merged, _read_toml(home / ".claude" / CONFIG_NAME))
        if project_dir:
            _overlay(merged, _read_toml(Path(project_dir) / ".claude" / CONFIG_NAME))

        inject = merged.get("inject", {})
        sweep = merged.get("sweep", {})
        return cls(
            inject_enabled=_as_bool(inject.get("enabled"), default=True),
            architecture_max_bytes=_as_int(
                inject.get("architecture_max_bytes"), default=DEFAULT_ARCHITECTURE_MAX_BYTES
            ),
            sweep_enabled=_as_bool(sweep.get("enabled"), default=True),
            sweep_model=_as_str(sweep.get("model"), default=DEFAULT_SWEEP_MODEL),
            min_exchanges=_as_int(sweep.get("min_exchanges"), default=DEFAULT_MIN_EXCHANGES),
        )


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


def _overlay(merged: dict[str, dict[str, object]], layer: dict[str, object]) -> None:
    """Merge one config layer's `[inject]`/`[sweep]` tables into `merged` per key."""
    for section in ("inject", "sweep"):
        table = layer.get(section)
        if isinstance(table, dict):
            merged.setdefault(section, {}).update(
                {k: v for k, v in table.items() if isinstance(k, str)}
            )


def _as_bool(value: object, *, default: bool) -> bool:
    """Coerce a config value to bool, falling back when it is not a bool."""
    return value if isinstance(value, bool) else default


def _as_int(value: object, *, default: int) -> int:
    """Coerce a config value to int, falling back on non-int/unparseable input."""
    # bool is an int subclass; exclude it so `enabled = true` never reads as 1.
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _as_str(value: object, *, default: str) -> str:
    """Coerce a config value to str, falling back when it is not a string."""
    return value if isinstance(value, str) else default
