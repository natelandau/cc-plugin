"""Generic per-stage hook driver.

`run_stage` loads a stage directory's `_registry.py`, gates each plugin by the
active profile and `disabled_hooks`, runs the survivors in declared order with
first-block-wins, and hands the result to the stage's `emit`. A missing or empty
registry makes the stage a noop. Every per-plugin failure (import or evaluate)
is swallowed so one broken plugin never wedges a tool call or a turn.
"""

from __future__ import annotations

import importlib
import sys
from typing import TYPE_CHECKING, Any, NoReturn

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from lib.config import Config
    from lib.io import Decision


def _warn(message: str) -> None:
    print(f"natelandau-toolkit: {message}", file=sys.stderr)  # noqa: T201


def _load_plugins(stage_dir: Path) -> list[tuple[str, frozenset[str]]]:
    """Return the stage's ordered (module_name, profiles) list, or [] if absent."""
    if str(stage_dir) not in sys.path:
        sys.path.insert(0, str(stage_dir))
    sys.modules.pop("_registry", None)  # never reuse another stage's registry
    try:
        registry = importlib.import_module("_registry")
    except Exception as exc:  # noqa: BLE001 - missing/broken registry => noop
        _warn(f"no usable registry in {stage_dir.name}: {exc}")
        return []
    return list(getattr(registry, "PLUGINS", []))


def collect(
    stage_dir: Path, event: dict[str, Any], cfg: Config
) -> tuple[Decision | None, list[str]]:
    """Run the stage's enabled plugins in order; return (blocking, contexts).

    The first plugin whose Decision blocks wins and short-circuits; advisory
    contexts from non-blocking plugins accumulate. Pure: never exits.
    """
    contexts: list[str] = []
    for module_name, profiles in _load_plugins(stage_dir):
        if cfg.profile not in profiles:
            continue
        sys.modules.pop(module_name, None)  # re-import fresh per process/run
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:  # noqa: BLE001 - resilience: never wedge
            _warn(f"plugin {module_name} failed to import: {exc}")
            continue
        plugin_id = getattr(module, "ID", module_name)
        if plugin_id in cfg.disabled_hooks:
            continue
        try:
            decision = module.evaluate(event, cfg)
        except Exception as exc:  # noqa: BLE001 - resilience: never wedge
            _warn(f"plugin {plugin_id} errored: {exc}")
            continue
        if decision is None:
            continue
        if decision.block:
            return decision, contexts
        if decision.context:
            contexts.append(decision.context)
    return None, contexts


def run_stage(
    *,
    stage_dir: Path,
    event: dict[str, Any],
    cfg: Config,
    emit: Callable[[Decision | None, list[str]], NoReturn],
) -> NoReturn:
    """Collect this stage's outcome and emit it in the stage's wire format."""
    blocking, contexts = collect(stage_dir, event, cfg)
    emit(blocking, contexts)
