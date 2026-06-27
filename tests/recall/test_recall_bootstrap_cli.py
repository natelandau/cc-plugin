"""Verify the recall-bootstrap.py CLI facade drives the engine end to end."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parent.parent.parent
    / "plugins"
    / "natelandau-recall"
    / "hooks"
    / "recall-bootstrap.py"
)

_GIT_REPO_VARS = frozenset(
    {
        "GIT_DIR",
        "GIT_COMMON_DIR",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_WORK_TREE",
    }
)


def _run(
    args: list[str], *, cwd: Path, env_overrides: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    base = {k: v for k, v in os.environ.items() if k not in _GIT_REPO_VARS}
    return subprocess.run(
        [str(SCRIPT), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env={**base, **env_overrides},
        check=False,
        timeout=60,
    )


def _seed_transcripts(home: Path, cwd: Path, names: list[str]) -> None:
    from recall import bootstrap  # ty: ignore[unresolved-import]

    tdir = bootstrap.transcripts_dir_for(cwd, home=home)
    tdir.mkdir(parents=True, exist_ok=True)
    for i, name in enumerate(names):
        # Use 20 entries (well above DEFAULT_MIN_EXCHANGES=10) so transcripts
        # clear the filter when the subprocess uses the default config.
        lines = [
            json.dumps({"type": "user", "message": {"content": f"question {j}"}})
            if j % 2 == 0
            else json.dumps(
                {
                    "type": "assistant",
                    "message": {"content": [{"type": "text", "text": f"answer {j}"}]},
                }
            )
            for j in range(20)
        ]
        (tdir / f"{name}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.utime(tdir / f"{name}.jsonl", (1000 + i, 1000 + i))


def test_discover_prints_manifest(tmp_path: Path) -> None:
    """Verify discover --all prints a JSON manifest excluding the live session."""
    # Given an isolated project with three transcripts seeded (live = newest)
    proj = tmp_path / "proj"
    proj.mkdir()
    home = tmp_path / "home"
    _seed_transcripts(home, proj, ["s1", "s2", "live"])
    env = {
        "HOME": str(home),
        "XDG_DATA_HOME": str(tmp_path / "data"),
        "XDG_STATE_HOME": str(tmp_path / "state"),
        "CLAUDE_PROJECT_DIR": str(proj),
    }

    # When the discover subcommand runs
    proc = _run(["discover", "--all"], cwd=proj, env_overrides=env)

    # Then it exits 0 and prints a JSON manifest omitting the live session
    assert proc.returncode == 0, proc.stderr
    manifest = json.loads(proc.stdout)
    assert [e["session_id"] for e in manifest] == ["s1", "s2"]  # live excluded


def test_apply_then_clean(tmp_path: Path) -> None:
    """Verify apply writes the store and clean removes the scratch dir without error."""
    # Given an isolated project with no transcripts
    proj = tmp_path / "proj"
    proj.mkdir()
    home = tmp_path / "home"
    env = {
        "HOME": str(home),
        "XDG_DATA_HOME": str(tmp_path / "data"),
        "XDG_STATE_HOME": str(tmp_path / "state"),
        "CLAUDE_PROJECT_DIR": str(proj),
    }
    plan = tmp_path / "plan.json"
    plan.write_text(
        json.dumps(
            {
                "learnings": [{"filename": "t.md", "content": "summary: x\n"}],
                "backlog": None,
                "processed_session_ids": ["s1"],
            }
        ),
        encoding="utf-8",
    )

    # When apply is called with a plan file
    proc = _run(["apply", str(plan)], cwd=proj, env_overrides=env)

    # Then it exits 0, returns JSON, and records the session in the ledger
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)
    assert result["ledger_added"] == 1
    # clean runs without error
    assert _run(["clean"], cwd=proj, env_overrides=env).returncode == 0
