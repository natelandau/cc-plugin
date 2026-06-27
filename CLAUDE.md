# CLAUDE.md

## Project overview

A Claude Code **marketplace** repo (`.claude-plugin/marketplace.json`) shipping two
independent plugins, each under `plugins/<name>/`. They ship together but share no
code or structure.

- **`natelandau-toolkit`** — PreToolUse/Stop safety hooks, on-demand skills, slash
  commands, subagents.
- **`natelandau-recall`** — project-memory hooks: SessionStart injects stored memory;
  SessionEnd/PreCompact run a detached headless "sweep" that distills the session into
  durable memory.

## Commands

```bash
uv run pytest                  # full suite (tests/ = toolkit, tests/recall/ = recall)
uv run pytest tests/recall     # one plugin's tests
uv run ruff check && uv run ruff format   # lint + format (run after any .py edit)
uv run ty check                # typecheck — the SOLE typechecker; ignore Pyright entirely
```

Tests resolve paths via `conftest.py` fixtures, so they run from any cwd. Skills,
commands, and agents are content (no test harness). Run the relevant suite before
committing a code change.

## Repo-wide gotchas & conventions

- **Live docs drift.** This repo tracks live Claude Code docs. Before authoring or
  modifying a hook/skill/command/agent, fetch the current page — index
  <https://code.claude.com/docs/llms.txt> (key: plugins-reference, hooks, skills,
  sub-agents). Don't work from memory.
- **`${CLAUDE_PLUGIN_ROOT}`.** On install the plugin dir moves, so every path in
  `hooks.json` (and any path-bearing config) must reference scripts via
  `${CLAUDE_PLUGIN_ROOT}/...`.
- **Entry scripts vs imported modules.** Hook entry scripts carry
  `#!/usr/bin/env -S uv run --script` + a `# /// script` block and are executable
  (`100755`; git tracks the mode bit). The modules they import (`hooks/lib/`,
  `hooks/recall/`) have no shebang/metadata and stay `100644`.
- **Stdlib only** in hook code; no third-party deps.
- **Read stdin via the plugin's `io.read_payload()`**, not bare `json.load` (it caps
  the read and fails open to `{}`). Payload fields are `tool_name`, `tool_input`,
  `cwd`, `transcript_path`, `stop_hook_active` — **not** `tool`/`parameters` (a hook
  keyed on those silently no-ops).
- **Hook exit codes:** `0` = allow (stdout = advisory text), `2` = block (stderr fed to
  the model). For Stop/PostToolUse a block is `{"decision":"block","reason":"..."}` on
  stdout with exit 0.
- **Fail open** on the hook's own failure — never wedge a tool call because input was
  unreadable or a state file unwritable. Use `lstat`, not `exists`, for "was this here
  before I touched it" gates (symlink-safe).
- **ruff targets `py314`** → `ruff format` drops parens on multi-exception `except`
  (`except (A, B):` → `except A, B:`, PEP 758). Don't revert it; ruff re-strips them.
- **Scratch dirs are gitignored and never committed:** `.agent/` (specs in
  `.agent/specs/`, plans in `.agent/plans/`) and `docs/` (session-local).

## natelandau-toolkit

Per-stage dispatcher (`hooks/<stage>.py`, a one-liner into `lib/dispatch.py`) →
`hooks/<stage>/_registry.py` (`PLUGINS` = ordered `(module, profiles)`) → plugin modules
exposing `ID` + `evaluate(event, cfg) -> Decision | None`. First-block-wins; per-plugin
exceptions are swallowed so one broken plugin never wedges a call. Only `pretooluse` is
wired; the other stages are ready noops. **Per-hook behavior lives in each
module's docstring + sibling `<hook>.rules.toml` — those are the source of truth, not
this file** (`ls hooks/pretooluse/` for the current set).

- **Config:** file-based cascade (global `~/.claude/natelandau-toolkit.toml` → project
  `$CLAUDE_PROJECT_DIR/.claude/...`; `[hooks.*]` tables deep-merge). `profile`
  (`minimal`|`standard`|`strict`) + `disabled_hooks` gate which hooks run; template at
  `hooks/natelandau-toolkit.toml.example`. Per-project additive
  `.../natelandau-toolkit/<hook>.rules.toml` may only ADD blocking rules and fails open
  if malformed.
- **Rule data:** declaration-order, first-match-wins. In `.rules.toml` use literal
  strings (`'...'`) for `pattern` so regex backslashes pass verbatim; patterns compile
  at load, so a bad regex fails loudly.
- **Stop gotcha:** the raw Stop payload has **no** assistant text. The dispatcher's
  `prepare` (`transcript.parse_stop`) adds `event["assistant_message"]` — read that;
  anything reaching for assistant text on the raw payload returns None silently.
- **Bash matching:** a regex on `--message`/`--force` misses `-am`/`-rf`/`-fr` and
  `-m"msg"`. Match the bundled/reordered short forms and add a regression case for each.
- **Adding a hook:** new `hooks/<stage>/<plugin>.py` (`ID` + `evaluate`, no
  shebang/exec bit) → register in `_registry.py` → `tests/test_<plugin>.py`. Wiring a
  noop stage on also needs a `hooks.json` block and removal from `STAGE_DISPATCHERS` in
  `tests/test_manifest.py` (the orphan guard).

## natelandau-recall

Standalone — **not** built on toolkit's harness (no dispatcher/registry/profiles).
Three thin entry scripts (`hooks/sessionstart.py`, `sessionend.py`, `precompact.py`)
wire a flat engine package `hooks/recall/`:

- `Store` (XDG paths + per-project key, plus consume-once `HANDOFF.md` baton IO via
  `read_handoff`/`delete_handoff`), `Injector` (the SessionStart memory block),
  `Sweep`/`Lock`/`ClaudeRunner` (the headless `claude -p` sweep), `RecallConfig`, plus
  pure `transcript`/`frontmatter`/`paths`/`io`/`headless`. Deep behavior is in each
  module's docstring.
- **Store paths have one source of truth: `paths.py`** (the dash-encoded project key).
  Python reaches it through `Store`; **skills MUST call the `hooks/recall-path.py`
  facade** (`--data-dir`/`--handoff`/`--backlog`/`--learnings`) to resolve a path,
  never re-derive the encoding in prose. A skill references it via
  `${CLAUDE_SKILL_DIR}/../../hooks/recall-path.py` (`${CLAUDE_PLUGIN_ROOT}` is a hook
  var, not a skill var). The script is executable (`100755`); the engine modules it
  imports stay `100644`. The companion **`hooks/recall-bootstrap.py`** facade (also
  `100755`) is the skill-facing entry for transcript discovery, staging, and backfill
  plan application; its engine is `hooks/recall/bootstrap.py` (`100644`).
- The **`recall-bootstrap` skill** (user-invoked) backfills the memory store from past
  session transcripts via parallel extractor subagents and a single user-approved merge.
- **Config is flat** `[inject]`/`[sweep]` TOML (`hooks/natelandau-recall.toml.example`),
  no profiles or `disabled_hooks`.
- The sweep runs **detached** (double-fork) so it outlives session teardown, with an
  `NL_RECALL_HEADLESS` env guard so the spawned agent's own hooks no-op (recursion
  guard).
- Tests in `tests/recall/` import the engine directly (`from recall.X import Y`).
  `tests/__init__.py` exists so the `tests/recall` dir is `tests.recall` and never
  shadows the `recall` engine package in one pytest process.

## Authoring skills / commands / agents

- A skill's entry file is exactly `skills/<name>/SKILL.md` and its description must start
  "Use when …"; use the `skill-creator` skill to author/revise (don't handcraft
  frontmatter). Shared procedure lives in `skills/shared/*.md`, linked by relative path.
- **Don't cross-reference sibling skills/commands inside a component body** — the reader
  is an agent executing that one component, often in an unrelated project. State the
  behavior directly (naming a hook it actually trips, e.g. `enforce_commit_message`, is
  fine).
- A rule that must **hold** (never force-push, never weaken a config) belongs in a
  PreToolUse hook, not skill prose — prose is a request, a hook is enforcement.
- Reach for a subagent only for verbose, self-contained, summarizable work where keeping
  output out of the orchestrator's context is the point (test-runner, doc-drift-reviewer,
  review-finder, review-verifier).

## Safety: never run destructive commands, even in tests

The toolkit hooks block destructive ops; their tests must exercise the gate without ever
letting the payload execute. Assume the hook fails to block **and** the command succeeds.

- Feed bash strings to the hook **as data on stdin** (`_bash(cmd)` helpers) — never via
  `subprocess`/`os.system`/a shell. Cloud/IaC payloads (`terraform destroy`,
  `aws s3 rb --force`, `gh repo delete`) target real remote state: same rule.
- Validate a pattern manually by piping a payload in, never by typing it in a real
  session:

  ```bash
  echo '{"tool_name":"Bash","tool_input":{"command":"rm -rf ~"}}' \
    | plugins/natelandau-toolkit/hooks/pretooluse.py   # exit 2 = blocked
  ```

- "Passes through" assertions use a benign payload (`echo hello`), not a defanged-looking
  destructive one.
