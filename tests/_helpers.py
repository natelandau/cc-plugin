"""Shared scaffolding for the toolkit hook tests.

Every hook suite needs to build a Bash PreToolUse payload and to import a hook
source file in-process for unit tests. Keeping both here stops the payload
shape and the importlib dance from drifting across the suites.
"""

from __future__ import annotations

import importlib.util
import sys
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path
    from types import ModuleType


def bash_payload(cmd: str) -> dict[str, Any]:
    """Build a Bash PreToolUse payload carrying `cmd` as the tool input."""
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": cmd},
    }


def load_hook_module(hooks_dir: Path, relpath: str, name: str) -> ModuleType:
    """Import a hook source file (`hooks_dir`/`relpath`) in-process under `name`.

    Puts hooks_dir on sys.path so the module's sibling imports (lib/, ...)
    resolve, and registers the module in sys.modules before exec so dataclass
    string-annotation resolution can find it -- a superset of what every
    individual suite needs.
    """
    sys.path.insert(0, str(hooks_dir))
    try:
        spec = importlib.util.spec_from_file_location(name, hooks_dir / relpath)
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)
