"""Tests for the generic per-stage dispatch driver."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest  # noqa: F401  # pytest discovers fixtures from this import

HOOKS = Path(__file__).resolve().parent.parent / "plugins" / "natelandau-toolkit" / "hooks"
sys.path.insert(0, str(HOOKS))

from lib import dispatch  # noqa: E402  # ty: ignore[unresolved-import]

# Decision is used inside the embedded plugin source strings, not directly here.
from lib.io import Decision  # noqa: E402, F401  # ty: ignore[unresolved-import]


class _Cfg:
    def __init__(self, profile="standard", disabled=()):
        self.profile = profile
        self.disabled_hooks = set(disabled)


def _stage(tmp_path: Path, plugins: dict[str, str], registry: str) -> Path:
    """Build a throwaway stage dir with plugin modules and a _registry.py."""
    d = tmp_path / "stage"
    d.mkdir()
    for name, body in plugins.items():
        (d / f"{name}.py").write_text(textwrap.dedent(body), encoding="utf-8")
    (d / "_registry.py").write_text(textwrap.dedent(registry), encoding="utf-8")
    return d


def test_empty_registry_is_noop(tmp_path):
    """Verify an empty PLUGINS registry yields no decision and no contexts."""
    d = _stage(tmp_path, {}, "PLUGINS = []")
    assert dispatch.collect(d, {}, _Cfg()) == (None, [])


def test_first_block_wins(tmp_path):
    """Verify the first blocking plugin in registry order wins and short-circuits."""
    d = _stage(
        tmp_path,
        {
            "a": "from lib.io import Decision\nID='a'\ndef evaluate(e,c): return Decision(block=True, reason='A')",
            "b": "from lib.io import Decision\nID='b'\ndef evaluate(e,c): return Decision(block=True, reason='B')",
        },
        "from lib.profiles import ALL\nPLUGINS=[('a',ALL),('b',ALL)]",
    )
    blocking, _contexts = dispatch.collect(d, {}, _Cfg())
    assert blocking.reason == "A"


def test_profile_gating_skips_plugin(tmp_path):
    """Verify a plugin is skipped when the active profile is outside its tier set."""
    d = _stage(
        tmp_path,
        {
            "a": "from lib.io import Decision\nID='a'\ndef evaluate(e,c): return Decision(block=True, reason='A')"
        },
        "from lib.profiles import STANDARD_UP\nPLUGINS=[('a',STANDARD_UP)]",
    )
    assert dispatch.collect(d, {}, _Cfg(profile="minimal")) == (None, [])


def test_disabled_hooks_skips_by_id(tmp_path):
    """Verify a plugin whose ID is in disabled_hooks is skipped."""
    d = _stage(
        tmp_path,
        {
            "a": "from lib.io import Decision\nID='alpha'\ndef evaluate(e,c): return Decision(block=True, reason='A')"
        },
        "from lib.profiles import ALL\nPLUGINS=[('a',ALL)]",
    )
    assert dispatch.collect(d, {}, _Cfg(disabled={"alpha"})) == (None, [])


def test_plugin_exception_is_swallowed(tmp_path):
    """Verify a raising plugin is skipped and later plugins still contribute."""
    d = _stage(
        tmp_path,
        {
            "boom": "ID='boom'\ndef evaluate(e,c): raise RuntimeError('x')",
            "ok": "from lib.io import Decision\nID='ok'\ndef evaluate(e,c): return Decision(block=False, context='hi')",
        },
        "from lib.profiles import ALL\nPLUGINS=[('boom',ALL),('ok',ALL)]",
    )
    blocking, contexts = dispatch.collect(d, {}, _Cfg())
    assert blocking is None
    assert contexts == ["hi"]
