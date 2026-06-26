# Contributing to natelandau-toolkit

This guide covers everything you need to add a hook plugin, skill, command, or agent to this repository. If you're here to install or configure the plugin rather than develop it, see the [README](README.md) instead.

## Contents

- [Dev environment setup](#dev-environment-setup)
- [Running the gates](#running-the-gates)
- [Repository layout](#repository-layout)
- [How hooks work](#how-hooks-work)
- [Adding a hook plugin to an existing stage](#adding-a-hook-plugin-to-an-existing-stage)
- [Turning on a currently-noop stage](#turning-on-a-currently-noop-stage)
- [Adding other components](#adding-other-components)
- [Test safety rules](#test-safety-rules)
- [Commit conventions](#commit-conventions)

---

## Dev environment setup

The only runtime dependency for the hook scripts is [uv](https://docs.astral.sh/uv/). The test suite and linters run through `uv` as well.

Clone the repo and sync the dev dependencies:

```bash
git clone https://github.com/natelandau/cc-plugin.git
cd cc-plugin
uv sync
```

### Live documentation requirement

Before authoring or modifying any hook, fetch the relevant docs page from the Claude Code documentation index:

```
https://code.claude.com/docs/llms.txt
```

The docs index lists direct URLs for hooks, skills, slash commands, and agents. Check there before assuming your training data reflects the current field names, exit codes, or payload shapes. The CLAUDE.md in this repo lists the exact URLs for each topic.

---

## Running the gates

Run these before every commit. They also run in CI.

```bash
# Run the full test suite
uv run pytest

# Run a single test file
uv run pytest tests/test_use_uv.py

# Lint and format
uv run ruff check .
uv run ruff format .

# Type check
uv run ty check
```

Pyright is not a project tool. `ty` is the sole typechecker; do not act on Pyright diagnostics.

---

## Repository layout

The repo is a marketplace catalog at the root and a single plugin under `plugins/natelandau-toolkit/`.

```
.claude-plugin/marketplace.json               Marketplace catalog
plugins/natelandau-toolkit/
  .claude-plugin/plugin.json                  Plugin manifest (name, version, description)
  hooks/
    hooks.json                                Event registration for wired stages
    pretooluse.py                             Dispatcher entry point for PreToolUse
    stop.py                                   Dispatcher entry point for Stop
    posttooluse.py                            Dispatcher for PostToolUse (unwired, noop)
    sessionstart.py                           Dispatcher for SessionStart (unwired, noop)
    sessionend.py                             Dispatcher for SessionEnd (unwired, noop)
    pretooluse/                               PreToolUse stage plugins
      _registry.py                            Ordered plugin list for this stage
      enforce_branch_protection.py
      enforce_commit_message.py
      config_protection.py
      protect_secrets.py
      protect_system.py
      use_uv.py
    stop/                                     Stop stage plugins
      _registry.py
      capture_followups.py
      stop_phrase_guard.py
    posttooluse/                              PostToolUse plugins (empty, noop)
      _registry.py
    sessionstart/                             SessionStart plugins (empty, noop)
      _registry.py
    sessionend/                               SessionEnd plugins (empty, noop)
      _registry.py
    lib/                                      Shared library code
      bash.py                                 Bash command-string clause splitting
      config.py                               Config loading and cascade
      dispatch.py                             Generic stage driver
      io.py                                   Payload reading and Decision type
      paths.py                                Symlink-hardened path containment
      profiles.py                             Profile tier constants (ALL, STANDARD_UP)
      rules.py                                TOML rule loading and matching
      state.py                                Session-keyed JSON state bridge
      transcript.py                           Stop event transcript reader
  skills/<name>/SKILL.md                      Skill entry files
  commands/<name>.md                          Slash commands
  agents/<name>.md                            Subagent definitions
tests/                                        Pytest characterization tests
```

---

## How hooks work

### The stage-dispatcher model

Each Claude Code hook event (PreToolUse, Stop, PostToolUse, etc.) has its own dispatcher script at `hooks/<stage>.py`. Each script is a one-liner calling `lib.dispatch.run_dispatcher("<stage>", ...)`, which owns the shared sequence: read the payload, optionally short-circuit via `skip_if` (the Stop re-fire guard), load the config, optionally transform the payload via `prepare` (the Stop transcript parse), run the stage, and emit via the stage's entry in `io.STAGE_EMITTERS`. Internally it calls `run_stage`, which drives the stage.

`run_stage` does the following:

1. Loads the stage's `hooks/<stage>/_registry.py` and reads its `PLUGINS` list.
2. Filters each plugin by the active profile and `disabled_hooks`.
3. Imports the surviving plugins in declared order and calls `evaluate(event, cfg)` on each.
4. Returns on the first block decision (first-block-wins). Advisory contexts from non-blocking plugins accumulate.

The registry and plugin modules are loaded by explicit file path (`importlib.util.spec_from_file_location` under a stage-qualified name), not by bare import name, so two stages may hold same-named files without colliding. An exception in any plugin is swallowed. One broken plugin never wedges a tool call.

### Plugin contract

A plugin is a Python module in `hooks/<stage>/` that exposes two module-level names:

- `ID` - a string slug used in block messages and `disabled_hooks` config.
- `evaluate(event, cfg) -> Decision | None` - the logic. Every plugin names the first parameter `event` (the dispatcher passes it positionally, so the name is convention, not contract). Return `None` to pass through, or a `Decision` to block or emit advisory context.

The plugin does its own self-filtering. For example, a plugin that only handles `Bash` tool calls checks `event.get("tool_name") != "Bash"` and returns `None` immediately for anything else. The dispatcher does not pre-filter by tool name at the plugin level.

A minimal plugin looks like this:

```python
from __future__ import annotations

from typing import TYPE_CHECKING, Any
from lib.io import Decision

if TYPE_CHECKING:
    from lib.config import Config

ID = "my-check"


def evaluate(event: dict[str, Any], cfg: Config) -> Decision | None:
    if event.get("tool_name") != "Bash":
        return None
    command = (event.get("tool_input") or {}).get("command", "")
    if "forbidden-command" not in command:
        return None
    return Decision.blocked(ID, "forbidden-command is not allowed")
```

No `__main__` block is needed. Plugins are imported by the dispatcher, not standalone scripts, so they carry no shebang, no `# /// script` metadata, and no exec bit (stay `100644`). Only the five `hooks/<stage>.py` dispatcher entry scripts are executable.

### Profile tiers

`_registry.py` tags each plugin with the profile tiers it runs in. Two constants cover the common cases:

- `ALL` - runs in `minimal`, `standard`, and `strict`.
- `STANDARD_UP` - runs in `standard` and `strict` only.

`minimal` is the safest-only tier. `standard` is the default. `strict` is reserved for future additions.

### Noop stages

Every Claude Code event stage has a directory and a `_registry.py`. An empty `PLUGINS` list makes that stage a noop. A stage without an entry in `hooks.json` is also never called by Claude Code. Both conditions apply to `posttooluse`, `sessionstart`, and `sessionend` today.

Turning on a stage requires two things:

1. The stage has at least one plugin registered in its `_registry.py`.
2. The stage has an entry block in `hooks/hooks.json`.

---

## Adding a hook plugin to an existing stage

These steps add a plugin to a stage that is already wired in `hooks.json` (today that is `pretooluse` and `stop`).

1. Create the plugin file at `hooks/<stage>/<your_plugin>.py`. The file must define `ID` and `evaluate` as described above. If the plugin is rule-driven, store rules in a sibling `<your_plugin>.rules.toml`.

2. Register the plugin in `hooks/<stage>/_registry.py` by appending an entry to `PLUGINS`:

   ```python
   from lib.profiles import ALL, STANDARD_UP

   PLUGINS: list[tuple[str, frozenset[str]]] = [
       # ... existing entries ...
       ("your_plugin", STANDARD_UP),  # or ALL
   ]
   ```

   The first element is the module stem (filename without `.py`). Order matters: first-block-wins.

3. Write tests in `tests/test_<your_plugin>.py`. Follow the project convention:

   - Per-plugin unit cases call `evaluate()` directly with a constructed event dict.
   - The dispatcher-level case exercises the full `<stage>.py` path via subprocess with a JSON payload on stdin.

4. Run the full suite and linters:

   ```bash
   uv run pytest
   uv run ruff check .
   uv run ruff format .
   uv run ty check
   ```

---

## Turning on a currently-noop stage

These steps wire a stage that currently has an empty `_registry.py` and no entry in `hooks.json`.

1. Add a plugin to the stage following [Adding a hook plugin to an existing stage](#adding-a-hook-plugin-to-an-existing-stage), steps 1-3.

2. Add the stage block to `hooks/hooks.json`:

   ```json
   "PostToolUse": [
     {
       "hooks": [
         {
           "type": "command",
           "command": "${CLAUDE_PLUGIN_ROOT}/hooks/posttooluse.py",
           "timeout": 15
         }
       ]
     }
   ]
   ```

   The snippet omits `"matcher"`. Omitting it means the dispatcher fires for every event of that type (fine for Stop and SessionStart/SessionEnd; for PreToolUse and PostToolUse you normally restrict it, e.g. `"matcher": "Read|Edit|Write|NotebookEdit|Bash"`). See `hooks.json` for the PreToolUse example.

3. Wire the stage in `hooks.json` (step 2 above). The orphan guard in `test_manifest.py` checks this registration. Once wired, remove the dispatcher filename from `STAGE_DISPATCHERS` in `tests/test_manifest.py` so the exemption does not go stale (that set exempts dispatchers that exist on disk but are not yet wired; leaving it in is harmless but is housekeeping to keep the exemption current). Run the full suite to confirm all tests pass.

---

## Adding other components

### New skill

Invoke the `skill-creator` skill inside Claude Code. It drafts the correct frontmatter and the required "Use when ..." description. Save the result to `skills/<name>/SKILL.md`. Optional supplementary content goes under `skills/<name>/references/`.

### New slash command

Create `commands/<name>.md` with this frontmatter:

```yaml
---
name: name-of-command
description: What the command does
argument-hint: "<optional arg description>"
---
```

The body is the prompt. Use `$ARGUMENTS` to reference user-supplied text. The command becomes `/<name>` after a plugin reload.

### New agent

Create `agents/<name>.md`. The `name` frontmatter field must match the file stem exactly, because `test_manifest.py` validates that. Add a `tools` allowlist for read-only agents. Dispatch via the `Agent` tool with `subagent_type: <name>`.

---

## Test safety rules

The hooks in this plugin block destructive shell operations. Tests must never execute a dangerous payload; they feed it to the hook as data on stdin.

The test pattern is:

```python
import json, subprocess
from pathlib import Path

def _bash(cmd: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": cmd}}

result = subprocess.run(
    [str(hook_script)],
    input=json.dumps(_bash("rm -rf ~")),
    capture_output=True,
    text=True,
)
assert result.returncode == 2  # blocked
```

The dangerous string is a value in a JSON dict. It never touches a shell.

Additional rules:

- Never call `subprocess.run` or `os.system` with the dangerous payload as a command. Only ever as stdin data.
- Never smoke-test a hook by typing the dangerous command into a real Claude Code session. If the hook is broken, the command runs.
- For pass-through assertions, use a benign payload like `{"command": "echo hello"}` or `{"command": "ls /tmp"}`. Do not use a "probably safe" destructive command.
- Cloud and IaC payloads (`terraform destroy --auto-approve`, `aws s3 rb --force`) are especially dangerous. Same rule applies.

---

## Commit conventions

Every commit message and pull request title must follow conventional-commit format. The `enforce_commit_message` hook validates this automatically before each `git commit` and on `gh pr create`.

The required format is:

```
<type>(<scope>): <subject>
```

Rules for the subject line:

- 70 characters maximum.
- Use the imperative, present tense: "add" not "added" or "adds".
- First letter lowercase.
- No trailing period.

Valid types:

| Type       | When to use                                                      |
| ---------- | ---------------------------------------------------------------- |
| `build`    | Changes to the build system or external dependencies             |
| `ci`       | CI configuration changes                                         |
| `docs`     | Documentation changes only                                       |
| `feat`     | A new feature                                                    |
| `fix`      | A bug fix                                                        |
| `perf`     | A change that improves performance                               |
| `refactor` | A change that neither fixes a bug nor adds a feature             |
| `style`    | Whitespace, formatting, or missing semicolons (no logic changes) |
| `test`     | Adding or correcting tests                                       |

The scope is the area of the codebase affected, for example `hooks`, `stop`, `skills`, or a specific plugin name.

Examples:

```
feat(pretooluse): add plugin to block direct database writes
fix(stop): prevent false positive on test output phrases
docs(skills): update safe-refactoring SKILL.md for new --quick flag
test(branch-protection): add case for squash-merge on protected branch
```
