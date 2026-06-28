# Contributing to natelandau-cc-plugin

This guide covers how to develop the plugins in this repository: hooks, skills, slash commands, and subagents. If you're here to install or configure the plugins rather than work on them, see the [README](README.md) instead.

This repo is a Claude Code marketplace shipping two independent plugins under `plugins/`. They release together but share no code and have different internal structures, so most sections below are split by plugin.

- `natelandau-toolkit`: PreToolUse and Stop safety hooks, on-demand skills, slash commands, and subagents.
- `natelandau-recall`: project-memory hooks. SessionStart injects stored memory; SessionEnd and PreCompact run a detached background sweep that distills the session into durable memory.

## Contents

- [Dev environment setup](#dev-environment-setup)
- [Running the gates](#running-the-gates)
- [Repository layout](#repository-layout)
- [How the toolkit hooks work](#how-the-toolkit-hooks-work)
- [Adding a toolkit hook to an existing stage](#adding-a-toolkit-hook-to-an-existing-stage)
- [Turning on a currently-noop toolkit stage](#turning-on-a-currently-noop-toolkit-stage)
- [How natelandau-recall works](#how-natelandau-recall-works)
- [Adding skills, commands, and agents](#adding-skills-commands-and-agents)
- [Test safety rules](#test-safety-rules)
- [Commit conventions](#commit-conventions)

---

## Dev environment setup

The only runtime dependency for the hook scripts is [uv](https://docs.astral.sh/uv/). The test suite and linters run through `uv` as well, and uv fetches the required Python (3.14+) on first run.

Clone the repo and sync the dev dependencies:

```bash
git clone https://github.com/natelandau/cc-plugin.git
cd cc-plugin
uv sync
```

### Live documentation requirement

Before authoring or modifying any hook, skill, command, or agent, fetch the relevant page from the Claude Code documentation index:

```
https://code.claude.com/docs/llms.txt
```

The index lists direct URLs for hooks, skills, slash commands, and agents. Check there before assuming your training data reflects the current field names, exit codes, or payload shapes. The CLAUDE.md in this repo lists the exact URLs for each topic.

---

## Running the gates

Run these before every commit. They also run in CI. Tests resolve paths through `conftest.py` fixtures, so they run from any working directory.

```bash
# Full suite (tests/ covers the toolkit, tests/recall/ covers recall)
uv run pytest

# One plugin's tests
uv run pytest tests/recall

# A single file
uv run pytest tests/test_use_uv.py

# Lint and format
uv run ruff check .
uv run ruff format .

# Type check
uv run ty check
```

Pyright is not a project tool. `ty` is the sole typechecker; don't act on Pyright diagnostics.

Skills, commands, and agents are content, not code, so they have no test harness. Run the suite before committing any code change.

---

## Repository layout

The marketplace catalog lives at the root; each plugin lives under `plugins/<name>/`.

```
.claude-plugin/marketplace.json               Marketplace catalog (lists both plugins)

plugins/natelandau-toolkit/
  .claude-plugin/plugin.json                  Plugin manifest (name, version, description)
  hooks/
    hooks.json                                Event registration for wired stages
    pretooluse.py                             Dispatcher entry point for PreToolUse
    stop.py                                   Dispatcher for Stop (unwired, noop)
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
    stop/ posttooluse/ sessionstart/ sessionend/   Empty noop stages (each has a _registry.py)
    lib/                                      Shared library: dispatch, config, io, rules,
                                              profiles, bash, paths, state, transcript
  skills/<name>/SKILL.md                      Skill entry files
  commands/<name>.md                          Slash commands
  agents/<name>.md                            Subagent definitions

plugins/natelandau-recall/
  .claude-plugin/plugin.json                  Plugin manifest
  hooks/
    hooks.json                                SessionStart, SessionEnd, PreCompact registration
    sessionstart.py sessionend.py precompact.py   Thin hook entry scripts
    recall-path.py                            Store-path resolver the skills call
    recall-bootstrap.py                       Backfill facade the recall-bootstrap skill calls
    recall/                                   Flat engine package (Store, Injector, Sweep, Bootstrap, etc.)
    prompts/                                  Sweep and bootstrap prompt templates (incl. shared _capture-criteria.md)
  skills/recall-*/SKILL.md                    Memory-curation, handoff, and backfill skills

tests/                                        Toolkit characterization tests
tests/recall/                                 Recall tests (import the engine directly)
```

### Path resolution and file modes

On install, the plugin directory moves, so every path in `hooks.json` (and any path-bearing config) must reference scripts through `${CLAUDE_PLUGIN_ROOT}/...`.

Hook entry scripts carry a `#!/usr/bin/env -S uv run --script` shebang plus a `# /// script` metadata block and are executable (`100755`; git tracks the mode bit). The modules they import (`hooks/lib/` in the toolkit, `hooks/recall/` in recall) have no shebang or metadata and stay `100644`. Hook code is stdlib-only; no third-party dependencies.

---

## How the toolkit hooks work

The toolkit uses a per-stage dispatcher model. This section applies only to `natelandau-toolkit`; recall has its own design, covered later.

### The stage-dispatcher model

Each Claude Code hook event (PreToolUse, Stop, and so on) has its own dispatcher script at `hooks/<stage>.py`. Each is a one-liner calling `lib.dispatch.run_dispatcher("<stage>", ...)`, which owns the shared sequence: read the payload, optionally short-circuit via `skip_if` (the Stop re-fire guard), load config, optionally transform the payload via `prepare` (the Stop transcript parse), run the stage, and emit through the stage's entry in `io.STAGE_EMITTERS`.

`run_stage` then does the following:

1. Loads the stage's `hooks/<stage>/_registry.py` and reads its `PLUGINS` list.
2. Filters each plugin by the active profile and `disabled_hooks`.
3. Imports the surviving plugins in declared order and calls `evaluate(event, cfg)` on each.
4. Returns on the first block decision (first-block-wins). Advisory contexts from non-blocking plugins accumulate.

Registry and plugin modules load by explicit file path (`importlib.util.spec_from_file_location` under a stage-qualified name), not by bare import name, so two stages may hold same-named files without colliding. An exception in any plugin is swallowed, so one broken plugin never wedges a tool call.

### Hook conventions

A few rules every plugin must follow:

- Read stdin through the plugin's `io.read_payload()`, not bare `json.load`. It caps the read and fails open to `{}`.
- Payload fields are `tool_name`, `tool_input`, `cwd`, `transcript_path`, and `stop_hook_active`, not `tool` or `parameters`. A hook keyed on the wrong names silently no-ops.
- Exit codes: `0` allows (stdout is advisory text), `2` blocks (stderr is fed back to the model). For Stop and PostToolUse, a block is `{"decision":"block","reason":"..."}` on stdout with exit 0.
- Fail open on the hook's own failure. Never wedge a tool call because input was unreadable or a state file unwritable.
- Use `lstat`, not `exists`, for "was this here before I touched it" gates, so symlinks are handled safely.

### The Stop transcript gotcha

The raw Stop payload contains no assistant text. The dispatcher's `prepare` step (`transcript.parse_stop`) adds `event["assistant_message"]`. Read that field. Anything reaching for assistant text on the raw payload returns `None` silently.

### Plugin contract

A plugin is a Python module in `hooks/<stage>/` that exposes two module-level names:

- `ID`: a string slug used in block messages and in `disabled_hooks` config.
- `evaluate(event, cfg) -> Decision | None`: the logic. Return `None` to pass through, or a `Decision` to block or emit advisory context.

A plugin does its own self-filtering. A plugin that only handles `Bash` calls checks `event.get("tool_name") != "Bash"` and returns `None` for everything else. The dispatcher does not pre-filter by tool name.

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

No `__main__` block is needed. Plugins are imported, not run, so they carry no shebang, no `# /// script` metadata, and no exec bit. Only the dispatcher entry scripts are executable.

### Rule data

Rule-driven hooks store their rules in a sibling `<hook>.rules.toml`, matched in declaration order, first-match-wins. In the TOML, use literal strings (`'...'`) for `pattern` so regex backslashes pass verbatim. Patterns compile at load time, so a bad regex fails loudly rather than in the hot path.

When matching Bash commands, remember that a regex on `--message` or `--force` misses bundled and reordered short forms like `-am`, `-rf`, `-fr`, and `-m"msg"`. Match those forms and add a regression case for each.

### Profile tiers

`_registry.py` tags each plugin with the profile tiers it runs in. Two constants from `lib/profiles.py` cover the common cases:

- `ALL`: runs in `minimal`, `standard`, and `strict`.
- `STANDARD_UP`: runs in `standard` and `strict` only.

`minimal` is the safest-only tier. `standard` is the default. `strict` is reserved for future additions.

### Noop stages

Every event stage has a directory and a `_registry.py`. An empty `PLUGINS` list makes that stage a noop, and a stage with no entry in `hooks.json` is never called by Claude Code. Both conditions apply to `posttooluse`, `sessionstart`, and `sessionend` today.

---

## Adding a toolkit hook to an existing stage

These steps add a plugin to a stage already wired in `hooks.json` (today, `pretooluse` and `stop`).

1. Create the plugin file at `hooks/<stage>/<your_plugin>.py` defining `ID` and `evaluate`. If it's rule-driven, store rules in a sibling `<your_plugin>.rules.toml`.

2. Register it in `hooks/<stage>/_registry.py` by appending to `PLUGINS`:

   ```python
   from lib.profiles import ALL, STANDARD_UP

   PLUGINS: list[tuple[str, frozenset[str]]] = [
       # ... existing entries ...
       ("your_plugin", STANDARD_UP),  # or ALL
   ]
   ```

   The first element is the module stem (filename without `.py`). Order matters: first-block-wins.

3. Write tests in `tests/test_<your_plugin>.py`:

   - Per-plugin unit cases call `evaluate()` directly with a constructed event dict.
   - At least one dispatcher-level case exercises the full `<stage>.py` path via subprocess with a JSON payload on stdin.

4. Run the gates:

   ```bash
   uv run pytest
   uv run ruff check .
   uv run ruff format .
   uv run ty check
   ```

The orphan guard in `tests/test_manifest.py` fails if a plugin file isn't registered in its `_registry.py`.

---

## Turning on a currently-noop toolkit stage

These steps wire a stage that currently has an empty `_registry.py` and no entry in `hooks.json`.

1. Add a plugin to the stage following the steps above, parts 1 through 3.

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

   Omitting `"matcher"` fires the dispatcher for every event of that type. That's fine for Stop and the session stages; for PreToolUse and PostToolUse you normally restrict it, for example `"matcher": "Read|Edit|Write|NotebookEdit|Bash"`. See the existing PreToolUse block in `hooks.json`.

3. Remove the dispatcher filename from `STAGE_DISPATCHERS` in `tests/test_manifest.py`. That set exempts dispatchers that exist on disk but aren't yet wired; once a stage is wired, drop it so the exemption stays current. Run the full suite to confirm.

---

## How natelandau-recall works

Recall is standalone. It does not use the toolkit's dispatcher, registry, or profile harness. Three thin hook entry scripts wire a flat engine package, alongside a `recall-path.py` resolver the skills call.

- `hooks/sessionstart.py` builds the SessionStart memory block and injects it. It also injects a pending `HANDOFF.md` handoff ahead of that block on any start except `resume`, deleting it only after a confirmed write and independent of `inject_enabled`.
- `hooks/sessionend.py` and `hooks/precompact.py` trigger the sweep that distills the session into memory.
- `hooks/recall-path.py` resolves store paths (`--data-dir`/`--handoff`/`--backlog`/`--learnings`) over `Store`. The recall skills call it instead of re-deriving the dash-encoded project key, so the encoding lives in one place (`paths.py`).
- `hooks/recall-bootstrap.py` is the facade the `recall-bootstrap` skill drives (`discover`/`apply`/`clean`) over `Bootstrap`.

The engine lives in `hooks/recall/`. The main pieces are:

- `Store`: resolves the XDG data and state roots and the per-project key, and owns small fail-open IO helpers, including the consume-once handoff (`read_handoff`/`delete_handoff`).
- `Injector`: assembles the SessionStart block (learnings index, one-line backlog pointer).
- `Sweep`, with `Lock` and `ClaudeRunner`: gates, detaches, runs, and validates the headless `claude -p` pass.
- `Bootstrap`: discovers, stages, and applies a backfill of the store from past transcripts.
- `RecallConfig`: the flat config object.
- Pure helpers: `transcript`, `frontmatter`, `paths`, `io`, `headless`, `safety` (the shared secret-scrub).

Each module's docstring carries its detailed behavior.

### The detached sweep and the recursion guard

The sweep runs the `claude -p` pass in a double-forked daemon so it outlives session teardown or compaction. Before spawning, it gates on `min_exchanges` so trivial sessions are skipped.

The spawned agent runs with `NL_RECALL_HEADLESS=1` in its environment. Recall's own entry scripts check for that variable and no-op when it's set, so the sweep's agent can't trigger another sweep. Preserve this guard in any change to the spawn path.

After the agent finishes, the sweep validates every file the agent reports writing and confirms it stays inside the project's memory store. The containment check in `paths.py` resolves symlinks on both sides, so a symlinked intermediate directory can't smuggle a write outside the store. The sweep prompt also treats the transcript as untrusted data.

### Config

Recall config is flat TOML with `[inject]` and `[sweep]` tables. There are no profiles and no `disabled_hooks`. The template is at `hooks/natelandau-recall.toml.example`. Defaults live in `hooks/recall/config.py`.

### Tests

Recall tests in `tests/recall/` import the engine directly, for example `from recall.store import Store`. A `tests/__init__.py` exists so the `tests/recall` directory resolves as `tests.recall` and never shadows the `recall` engine package within one pytest process. The manifest test for recall is `tests/recall/test_recall_manifest.py`.

---

## Adding skills, commands, and agents

Skills, slash commands, and subagents are content files. They live under the plugin that ships them (most under `natelandau-toolkit`; recall ships the `recall-review`, `recall-backlog`, and `recall-handoff` skills).

### New skill

Invoke the `skill-creator` skill inside Claude Code. It drafts the correct frontmatter and the required "Use when ..." description. Save the result to `skills/<name>/SKILL.md`. Optional supplementary content goes under `skills/<name>/references/`. Shared procedure goes in `skills/shared/*.md`, linked by relative path.

Don't cross-reference sibling skills or commands inside a component body. The reader is an agent executing that one component, often in an unrelated project, so state the behavior directly. Naming a hook the component actually trips, for example `enforce_commit_message`, is fine.

A rule that must hold (never force-push, never weaken a config) belongs in a PreToolUse hook, not skill prose. Prose is a request; a hook is enforcement.

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

Create `agents/<name>.md`. The `name` frontmatter field must match the file stem exactly, because the manifest test validates it. Add a `tools` allowlist for read-only agents. Reach for a subagent only for verbose, self-contained, summarizable work where keeping output out of the orchestrator's context is the point, such as `test-runner` or `doc-drift-reviewer`. Dispatch via the `Agent` tool with `subagent_type: <name>`.

---

## Test safety rules

The toolkit hooks block destructive shell operations. Tests must never execute a dangerous payload; they feed it to the hook as data on stdin. Assume the hook fails to block and the command succeeds, then write the test so that's still safe.

The pattern is:

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
- For pass-through assertions, use a benign payload like `{"command": "echo hello"}`. Don't use a "probably safe" destructive command.
- Cloud and IaC payloads (`terraform destroy --auto-approve`, `aws s3 rb --force`, `gh repo delete`) target real remote state. The same rule applies.

To validate a pattern manually, pipe a payload into the hook directly:

```bash
echo '{"tool_name":"Bash","tool_input":{"command":"rm -rf ~"}}' \
  | plugins/natelandau-toolkit/hooks/pretooluse.py   # exit 2 = blocked
```

---

## Commit conventions

Every commit message and pull request title must follow conventional-commit format. The toolkit's `enforce_commit_message` hook validates this automatically before each `git commit` and on `gh pr create`.

The required format is:

```
<type>(<scope>): <subject>
```

Rules for the subject line:

- 70 characters maximum.
- Imperative, present tense: "add" not "added" or "adds".
- First letter lowercase.
- No trailing period.

Valid types:

| Type       | When to use                                                      |
| ---------- | ---------------------------------------------------------------- |
| `build`    | Changes to the build system or external dependencies             |
| `ci`       | CI configuration changes                                          |
| `docs`     | Documentation changes only                                        |
| `feat`     | A new feature                                                     |
| `fix`      | A bug fix                                                         |
| `perf`     | A change that improves performance                               |
| `refactor` | A change that neither fixes a bug nor adds a feature             |
| `style`    | Whitespace, formatting, or missing semicolons (no logic changes) |
| `test`     | Adding or correcting tests                                        |

The scope is the area affected, for example `hooks`, `stop`, `recall`, `skills`, or a specific plugin name.

Examples:

```
feat(pretooluse): add plugin to block direct database writes
fix(stop): prevent false positive on test output phrases
feat(recall): skip the sweep below the minimum exchange count
test(branch-protection): add case for squash-merge on protected branch
```
