"""Generic per-stage hook driver.

`run_dispatcher` is the full entry sequence every stage script shares (read
payload, load config, optionally transform/short-circuit, run the stage,
emit). `run_stage` loads a stage directory's `_registry.py`, gates each plugin
by the active profile and `disabled_hooks`, runs the survivors in declared
order with first-block-wins, and hands the result to the stage's `emit`. A
missing or empty registry makes the stage a noop. Every per-plugin failure
(import or evaluate) is swallowed so one broken plugin never wedges a tool call
or a turn.

Registry and plugin modules are loaded by explicit file path (not by bare
name), so two stages may hold same-named files without colliding and the
driver never mutates `sys.path` or `sys.modules` to disambiguate them.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, NoReturn

from lib.config import load_config
from lib.io import STAGE_EMITTERS, read_payload

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import ModuleType

    from lib.config import Config
    from lib.io import Decision

# Repo `hooks/` dir (this file is hooks/lib/dispatch.py), the parent of every
# stage dir; `run_dispatcher` resolves a stage's dir under it by name.
_HOOKS_ROOT = Path(__file__).resolve().parent.parent


def _warn(message: str) -> None:
    print(f"natelandau-toolkit: {message}", file=sys.stderr)  # noqa: T201


def _load_module(unique_name: str, path: Path) -> ModuleType:
    """Execute a module from an explicit file path, bypassing sys.path lookup.

    Loading by path rather than by bare import name means two stages can hold
    same-named files without colliding, and the driver needs neither a
    `sys.path` insert nor a `sys.modules` pop to keep them apart: `unique_name`
    is stage-qualified, so each stage's modules occupy their own cache slots.
    The module's own `from lib...` imports still resolve via `sys.path`, where
    the dispatcher script has already placed the hooks root.

    The module is registered in `sys.modules` under `unique_name` *before*
    execution because a slotted dataclass (`@dataclass(slots=True)`) recreates
    its class and looks itself up via `sys.modules[cls.__module__]` mid-exec;
    an unregistered module makes that lookup fail. Each call re-creates and
    re-executes the module, overwriting any prior entry under the same name. If
    execution raises, the half-initialized module is evicted (as
    `importlib.import_module` does) so a broken plugin never leaves a corrupt
    entry cached under its name.
    """
    spec = importlib.util.spec_from_file_location(unique_name, path)
    if spec is None or spec.loader is None:
        msg = f"cannot load module from {path}"
        raise ImportError(msg)
    module = importlib.util.module_from_spec(spec)
    sys.modules[unique_name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(unique_name, None)
        raise
    return module


def _load_plugins(stage_dir: Path) -> list[tuple[str, frozenset[str]]]:
    """Return the stage's ordered (module_name, profiles) list, or [] if absent."""
    try:
        registry = _load_module(f"_registry_{stage_dir.name}", stage_dir / "_registry.py")
    except Exception as exc:  # noqa: BLE001 - missing/broken registry => noop
        _warn(f"no usable registry in {stage_dir.name}: {exc}")
        return []
    return list(getattr(registry, "PLUGINS", []))


def collect(
    stage_dir: Path, event: dict[str, Any], cfg: Config
) -> tuple[Decision | None, list[str]]:
    """Run the stage's enabled plugins in order; return (decision, contexts).

    Decision precedence is deny > ask > none: the first plugin that denies
    short-circuits and wins; the first plugin that asks is held but later
    plugins may still upgrade to a deny; advisory contexts accumulate
    regardless. Pure: never exits.
    """
    contexts: list[str] = []
    pending_ask: Decision | None = None
    for module_name, profiles in _load_plugins(stage_dir):
        if cfg.profile not in profiles:
            continue
        try:
            module = _load_module(
                f"{stage_dir.name}_{module_name}", stage_dir / f"{module_name}.py"
            )
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
        if decision.ask and pending_ask is None:
            pending_ask = decision
        if decision.context:
            contexts.append(decision.context)
    return pending_ask, contexts


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


def run_dispatcher(
    stage_name: str,
    *,
    prepare: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    skip_if: Callable[[dict[str, Any]], bool] | None = None,
) -> NoReturn:
    """Run a stage end to end; the body every dispatcher script reduces to.

    Reads the payload, optionally short-circuits via `skip_if` (the Stop
    re-fire guard), loads config, optionally transforms the payload via
    `prepare` (the Stop transcript parse), then runs the stage and emits in its
    wire format via the stage's entry in `STAGE_EMITTERS`. The five dispatcher
    scripts differ only in these three values, so each is one call to this.

    Args:
        stage_name: The stage's dir name under the hooks root, also its
            `STAGE_EMITTERS` key (e.g. "pretooluse", "stop").
        prepare: Transforms the raw payload into the event dict each plugin
            sees. Defaults to passing the payload through unchanged.
        skip_if: When it returns True for the raw payload, exit 0 before any
            plugin runs (e.g. the Stop `stop_hook_active` re-fire guard).
    """
    payload = read_payload()
    if skip_if is not None and skip_if(payload):
        sys.exit(0)
    cfg = load_config()
    event = prepare(payload) if prepare is not None else payload
    run_stage(
        stage_dir=_HOOKS_ROOT / stage_name,
        event=event,
        cfg=cfg,
        emit=STAGE_EMITTERS[stage_name],
    )
