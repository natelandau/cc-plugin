"""SessionEnd/PreCompact plugin: spawn the detached memory sweep, then return.

The deterministic gating (lock, threshold, transcript window) runs inline; the
heavy `claude -p` pass runs in a detached child that outlives session teardown
(verified by spike). Always returns None — this stage emits nothing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from lib import sweep

if TYPE_CHECKING:
    from lib.config import Config

ID = "run-sweep"


def evaluate(event: dict[str, Any], cfg: Config) -> None:
    """Trigger the memory sweep as a side effect; never blocks."""
    sweep.trigger(event, cfg)
