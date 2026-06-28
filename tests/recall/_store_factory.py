"""Shared in-memory Store factory and transcript builder for recall tests.

Several test modules need a Store rooted at a tmp_path with no real project
resolution or filesystem IO, and several need to fabricate a JSONL transcript.
Keeping both here stops the constructor call and the transcript entry shape from
drifting across the suite.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from recall.store import Store  # ty: ignore[unresolved-import]

if TYPE_CHECKING:
    from pathlib import Path


def store_at(tmp_path: Path) -> Store:
    """Build a Store rooted at `tmp_path`/data and `tmp_path`/state (constructs only, no IO)."""
    return Store(key="k", data_dir=tmp_path / "data", state_dir=tmp_path / "state")


def write_transcript(path: Path, *, exchanges: int, first_user: str = "hello") -> None:
    """Write a JSONL transcript of `exchanges` interleaved user/assistant text messages.

    The first user message is `first_user` so a test can plant the sweep
    signature; the rest are filler. Shared by the bootstrap engine and CLI tests
    so the transcript entry shape lives in exactly one place.
    """
    lines: list[str] = []
    for i in range(exchanges):
        text = first_user if i == 0 else f"msg {i}"
        if i % 2 == 0:
            lines.append(json.dumps({"type": "user", "message": {"content": text}}))
        else:
            lines.append(
                json.dumps(
                    {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}
                )
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
