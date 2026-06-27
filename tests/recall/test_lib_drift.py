"""Verify the drift-guarded shared lib modules stay byte-identical across plugins."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
TOOLKIT = ROOT / "plugins" / "natelandau-toolkit" / "hooks" / "lib"
RECALL = ROOT / "plugins" / "natelandau-recall" / "hooks" / "lib"

# Only genuinely generic modules are shared verbatim. io/config/transcript
# legitimately diverge (recall-specific emitters, config name, added windowing)
# and are intentionally excluded.
SHARED_MODULES = ("dispatch.py", "paths.py", "profiles.py")


@pytest.mark.parametrize("module", SHARED_MODULES)
def test_shared_lib_module_is_byte_identical(module: str) -> None:
    """Verify a vendored shared module matches the toolkit source exactly."""
    # Given the toolkit and recall copies of a shared module
    toolkit = (TOOLKIT / module).read_bytes()
    recall = (RECALL / module).read_bytes()
    # Then they are byte-for-byte identical (drift fails loudly)
    assert toolkit == recall, (
        f"{module} diverged between plugins; re-sync or move it out of SHARED_MODULES "
        f"with a comment explaining the divergence"
    )
