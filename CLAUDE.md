# CLAUDE.md

## Project overview

A Claude Code **plugin** named `natelandau-toolkit`: the user's personal Claude
Code config (PreToolUse / Stop hooks, on-demand skills, slash commands, subagents)
as one installable package. The repo is a marketplace catalog at the root and a
single plugin under `plugins/natelandau-toolkit/` (the marketplace's
`source: "./plugins/natelandau-toolkit"` points at it).

## Commands

```bash
uv run pytest                                  # full hook test suite
uv run pytest tests/test_branch_protection.py  # one file
uv run ruff check && uv run ruff format        # lint + format (run after any .py edit)
uv run ty check                                # typecheck (the sole typechecker; ignore Pyright)
```

Tests are pytest-based and resolve hook paths via fixtures in `tests/conftest.py`,
so they run from any cwd. Skills and commands have no test harness (content, not code).
**Always run the relevant suite before committing a hook change.**

## Live documentation

This plugin tracks live Claude Code docs, which drift. Before authoring or modifying
any component, fetch the relevant page so you work from current syntax, not memory.
Index: <https://code.claude.com/docs/llms.txt>. Key pages: plugins-reference (manifest,
component dirs, slash commands), hooks (events, payloads, exit codes), skills, sub-agents.

## Layout

```
.claude-plugin/marketplace.json                  Marketplace catalog
plugins/natelandau-toolkit/
  .claude-plugin/plugin.json                     Plugin manifest
  hooks/hooks.json                               Event registration (references scripts via ${CLAUDE_PLUGIN_ROOT})
  hooks/<stage>.py                               One dispatcher per stage (pretooluse, posttooluse, stop, sessionstart, sessionend)
  hooks/<stage>/_registry.py                     Ordered (module_name, profiles) list; empty = noop stage
  hooks/<stage>/<plugin>.py                      Plugin module: exposes ID + evaluate(event, cfg)
  hooks/<stage>/<plugin>.rules.toml              Optional rule data for a plugin
  hooks/lib/                                      Shared scaffolding: io, config, dispatch, profiles, rules, transcript, bash, paths, state
  skills/<name>/SKILL.md (+ references/)         On-demand skill guidance
  skills/shared/                                 Content shared by 2+ skills (no SKILL.md; linked by relative path)
  commands/<name>.md                             Slash commands
  agents/<name>.md                               Subagent definitions
tests/test_*.py                                  Hook characterization tests
```

On install, Claude Code clones the repo and sets `${CLAUDE_PLUGIN_ROOT}` to the
installed plugin dir. All path-bearing config (`hooks.json`, etc.) **must** reference
scripts via `${CLAUDE_PLUGIN_ROOT}/...` so they resolve regardless of install location.

## Hooks

One dispatcher script per Claude Code stage. Each dispatcher is a one-liner calling
`run_dispatcher("<stage>", ...)`; `lib/dispatch.py` is the generic driver. It reads the
stage's `_registry.py` (`PLUGINS` = ordered `(module_name, profiles)` list, declaration
order = run order), gates each plugin by `cfg.profile` and `cfg.disabled_hooks`, runs
survivors with **first-block-wins**, and swallows per-plugin exceptions so one broken
plugin never wedges a tool call. An empty `PLUGINS` list makes the stage a noop.

**Plugin contract.** Each `hooks/<stage>/<plugin>.py` exposes `ID` (slug used in
`disabled_hooks` and block messages) and `evaluate(event: dict, cfg: Config) -> Decision | None`.
The plugin self-filters on the fields it handles (e.g. `event.get("tool_name") == "Bash"`).
Read the module docstrings and sibling `.rules.toml` files for per-hook behavior and
carve-outs — they are the source of truth, not this file.

**Wired stages.** Only `pretooluse` and `stop` have plugins and are wired in `hooks.json`;
`posttooluse`/`sessionstart`/`sessionend` exist as ready noop stages. Wiring a stage on
takes two steps: add the plugin to `_registry.py`, then add the dispatcher block to
`hooks.json`. `tests/test_manifest.py`'s `STAGE_DISPATCHERS` set lists the not-yet-wired
scripts so the orphan guard ignores them; move a script out of that set when you wire it.

**Current hooks** (behavior in each module's docstring):

- `pretooluse/enforce_branch_protection` — blocks destructive git ops + file mods on
  main/master (incl. merge-commit-creating `merge`/`pull`). Rules are in-script tuples
  (bypass logic for worktrees/squash/`/tmp`/gitignored targets lives alongside).
- `pretooluse/protect_secrets` — blocks read/edit/write/exfil of sensitive files.
- `pretooluse/protect_system` — blocks system-destructive Bash.
- `pretooluse/enforce_commit_message` — conventional-commit format on `git commit` and `gh pr` titles.
- `pretooluse/config_protection` — blocks edits that weaken a linter/formatter/typechecker config.
- `pretooluse/use_uv` — non-blocking nudge toward `uv run`.
- `stop/stop_phrase_guard` — blocks Stop turns whose assistant text dodges or pauses/asks.
- `stop/capture_followups` — blocks a Stop turn that names deferred work unless the backlog was written this turn.

### Configuration

File-based, cascading: global loaded first, then project overrides per key (`[hooks.*]`
tables deep-merge; scalars/lists are replaced).

- Global: `~/.claude/natelandau-toolkit.toml`
- Project: `$CLAUDE_PROJECT_DIR/.claude/natelandau-toolkit.toml`
- Template: `hooks/natelandau-toolkit.toml.example`

`profile` (`minimal` | `standard` (default) | `strict`) selects the tier; `disabled_hooks`
force-disables by ID. Tiers: `minimal` = branch-protection, protect-secrets, protect-system,
stop-phrase-guard; `standard` adds commit-message, config-protection, use-uv, capture-followups;
`strict` = standard (reserved). Per-hook options go under `[hooks.<id>]` (currently only
`[hooks.capture-followups].backlog`, default `.agent/BACKLOG.md`).

**Per-project additive rules.** Rule-driven hooks also read
`$CLAUDE_PROJECT_DIR/.claude/natelandau-toolkit/<hook>.rules.toml`, same schema as the
built-in file. These are **additive-only** (may add blocking rules, never weaken a built-in
one; to disable a hook use `disabled_hooks`). A malformed rules file **fails open**: warn to
stderr, ignore that file, keep enforcing the rest. Loader is `lib/rules.py`.

## Conventions

### Hook scripts

- **Shebang + exec bit on dispatchers only.** The five `hooks/<stage>.py` dispatchers carry
  `#!/usr/bin/env -S uv run --script` + inline `# /// script` metadata and must be executable
  (git tracks the mode bit). Plugin modules and `hooks/lib/` are imported (via
  `spec_from_file_location`), never run as scripts: no shebang, no metadata, mode `100644`.
- **Stdlib only.** Plugins may import the sibling `hooks/lib/` package; no third-party deps.
- **Read stdin via `lib.io.read_payload()`**, not bare `json.load`. It caps the read and fails
  open to `{}`. Payload field names are `tool_name`, `tool_input`, `cwd`, `transcript_path`,
  `stop_hook_active`, etc. — **not** `tool` or `parameters` (a hook keyed on those silently
  does nothing).
- **Exit codes:** `0` = allow (stdout = advisory text); `2` = block (stderr fed back to model);
  other = non-blocking error. For Stop/PostToolUse block decisions, emit
  `{"decision":"block","reason":"..."}` to stdout with exit 0.
- **Fail open on the hook's own failure** — never wedge a tool call because input was unreadable
  or a state file unwritable.
- **`lstat`, not `exists`**, for "was this here before I touched it" gates (symlink-safe).
- **Quote- and combined-flag-aware Bash matching:** a regex on `--message`/`--force` misses
  `-am`/`-rf`/`-fr` and `-m"msg"`. Match the bundled/reordered short forms and add a regression
  case for each.

### Stop hook transcript (critical gotcha)

The raw Stop payload does **not** contain assistant text. The Stop dispatcher's `prepare`
(`transcript.parse_stop`) reads the JSONL once and adds `assistant_message` + `entries` to the
event dict. Stop plugins read `event["assistant_message"]`; anything reaching for the assistant
text on the raw payload returns None silently. Transcript parsing is centralized in
`lib/transcript.py` — plugins never read the JSONL themselves.

### Rule data

Iteration is declaration order, first-match-wins. Two storage shapes: in-script tuples
(`enforce_branch_protection`, because bypass logic lives alongside) and sibling
`<hook>.rules.toml` loaded through `lib/rules.py`. TOML authoring: use **literal strings**
(`'...'`) for `pattern` so regex backslashes pass verbatim; patterns containing `'` use
triple-quoted literals. Patterns compile at load time, so a bad regex fails loudly, not in the
hot path. Schema and operators are documented in `lib/rules.py` and exercised by
`tests/test_lib_rules.py`.

### Style

- Run `ruff check`, `ruff format`, `ty check` after editing any Python file.
- Ruff targets `py314`, so `ruff format` drops parens around multi-exception `except` clauses
  (`except (A, B):` → `except A, B:`, valid 3.14 syntax per PEP 758). Don't "fix" it back; ruff
  re-strips them.
- `docs/` is gitignored (session-local specs/plans). Don't commit them.
- Don't cross-reference sibling skills/commands inside a skill/command *body* — the reader is an
  agent executing that one component, often in an unrelated project. State the behavior directly.
  (Naming a hook the component actually trips, e.g. `enforce_commit_message`, is fine.)

### Skills / commands / agents

- Skill entry file is exactly `skills/<name>/SKILL.md`; description must start "Use when ...".
  Use `skill-creator` to author/revise (don't handcraft frontmatter). Shared procedure lives in
  `skills/shared/*.md`, linked by relative path.
- A rule that must *hold* (never force-push, never weaken a config) belongs in a PreToolUse hook,
  not skill prose — prose is a request, a hook is enforcement.
- Reach for a subagent only for verbose, self-contained, summarizable work where keeping output
  out of the orchestrator's context is the point (test-runner, doc-drift-reviewer, review-finder,
  review-verifier). Dedupe shared *procedure* with `skills/shared/*.md`, not by spinning up an agent.

## Adding a hook plugin

1. Create `hooks/<stage>/<plugin>.py` with `ID` and `evaluate(event, cfg)` (module docstring at
   top, no shebang/metadata/exec bit). Add a sibling `.rules.toml` if rule-driven.
2. Add `("<plugin>", <profiles>)` to that stage's `_registry.py` `PLUGINS` (order = run order,
   safety-first). `lib/profiles.py` has `ALL` and `STANDARD_UP`.
3. Add `tests/test_<plugin>.py`: per-plugin cases calling `evaluate()` directly, plus at least
   one dispatcher-level case piping a JSON payload to `hooks/<stage>.py`.
4. If the stage was a noop, add its block to `hooks.json` and remove the dispatcher from
   `STAGE_DISPATCHERS` in `tests/test_manifest.py`.
5. `uv run pytest`, then `uv run ruff check && uv run ruff format`.

The `test_manifest.py` orphan guard catches any plugin not listed in its `_registry.py`.

## Safety: never run destructive commands, even in tests

These hooks block destructive ops; their tests must exercise the gate without ever letting the
payload execute. Assume the hook fails to block **and** the command succeeds.

- Tests feed bash strings to the hook **as data on stdin** (see `_bash(cmd)` helpers). Never
  invoke the payload via `subprocess`/`os.system`/a shell.
- Never smoke-test by typing a dangerous command into a real session. To validate a pattern
  manually, pipe a payload into the hook directly:

  ```bash
  echo '{"tool_name":"Bash","tool_input":{"command":"rm -rf ~"}}' \
    | plugins/natelandau-toolkit/hooks/pretooluse.py   # exit 2 = blocked
  ```

- Cloud/IaC payloads (`terraform destroy`, `aws s3 rb --force`, `gh repo delete`) target real
  remote state — same rule, only ever a string fed to the hook.
- "Passes through" assertions use a benign payload (`echo hello`), not a defanged-looking
  destructive one.
