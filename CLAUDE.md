# CLAUDE.md

## Project overview

A Claude Code **plugin** named `natelandau-toolkit` that consolidates the
user's personal Claude Code configuration in one installable package:
PreToolUse / Stop hooks, on-demand skills, and slash commands.
Distributed as a single repository so it can be installed via Claude
Code's plugin system without hand-editing `settings.json`.

## Live documentation

This plugin tracks the live Claude Code documentation. Before authoring or
modifying any component, fetch the relevant page from
<https://code.claude.com/docs/> so you're working from current syntax,
fields, and semantics rather than memory:

| Topic                                              | URL                                                    |
| -------------------------------------------------- | ------------------------------------------------------ |
| Plugin manifest, component dirs, install mechanics | <https://code.claude.com/docs/en/plugins-reference.md> |
| Plugin authoring guide                             | <https://code.claude.com/docs/en/plugins.md>           |
| Hook events, payloads, exit codes, matchers        | <https://code.claude.com/docs/en/hooks.md>             |
| Hook authoring guide                               | <https://code.claude.com/docs/en/hooks-guide.md>       |
| Skill format and authoring                         | <https://code.claude.com/docs/en/skills.md>            |
| Subagent definitions                               | <https://code.claude.com/docs/en/sub-agents.md>        |

Slash commands are covered in the plugins reference.

## Layout

The repo is a marketplace catalog at the root and a single plugin under
`plugins/natelandau-toolkit/`. The marketplace's `source: "./plugins/natelandau-toolkit"`
points Claude Code at the plugin directory.

```
.claude-plugin/marketplace.json                       Marketplace catalog (lists this plugin)
plugins/natelandau-toolkit/.claude-plugin/plugin.json Plugin manifest (name, description, author, version)
plugins/natelandau-toolkit/hooks/hooks.json           Event registration; references scripts via ${CLAUDE_PLUGIN_ROOT}
plugins/natelandau-toolkit/hooks/*.py                 Hook scripts, each a self-contained `uv run --script`
plugins/natelandau-toolkit/skills/<name>/SKILL.md     On-demand guidance loaded by the skill router
plugins/natelandau-toolkit/skills/<name>/references/  Optional supplementary content for a skill
plugins/natelandau-toolkit/commands/<name>.md         Slash commands invoked by the user
plugins/natelandau-toolkit/agents/<name>.md           Subagent definitions
tests/test_*.py                                       Hook characterization test harnesses (no pytest dep)
```

On install, Claude Code clones the repo under `~/.claude/plugins/...` and
sets `${CLAUDE_PLUGIN_ROOT}` to the installed `plugins/natelandau-toolkit/`
directory. All path-bearing config (`hooks.json`, etc.) must reference
scripts via `${CLAUDE_PLUGIN_ROOT}/...` so they resolve regardless of
install location.

## Hooks

Each hook is a self-contained `uv run --script` registered in
`hooks/hooks.json`. Read the script docstring + sibling `.rules.toml`
for behavior; the notes below cover only non-obvious gotchas,
cross-component decisions, and design rationale.

### `hooks/enforce_branch_protection.py` (PreToolUse)

Blocks destructive git ops on any branch and file modifications on
`main`/`master`. Non-obvious carve-outs:

- Linked worktrees pass through, so editing inside
  `.worktrees/<branch>/` while the parent repo is on `master` works.
- In-progress squash merges allow `git commit` on a protected branch.
- `/tmp/*`-only file ops pass through.

Rule data is two in-script tuples (`DESTRUCTIVE_RULES`,
`PROTECTED_FILE_MOD_RULES`). Kept in-script rather than TOML because
the bypass logic (worktree/squash/`/tmp` detection) lives alongside
the rules.

### `hooks/stop_phrase_guard.py` (Stop)

Blocks Stop turns whose assistant text matches a pattern in
`stop_phrase_guard.rules.toml`.

**Critical gotcha:** Stop hook input does NOT provide a
`last_assistant_message` field. The hook reads `transcript_path`
instead (see "Stop hook transcript shape" below). Any code reaching
for `last_assistant_message` is broken and exits 0 silently.

Be cautious about broad patterns (`getting long`, `next session`);
they false-positive in legitimate contexts.

### `hooks/protect_secrets.py` (PreToolUse)

Blocks reads/edits/writes/exfiltration of sensitive files. Rules in
`protect_secrets.rules.toml`; threshold via
`CLAUDE_PROTECT_SECRETS_LEVEL` (default `high`).

### `hooks/protect_system.py` (PreToolUse)

Blocks system-destructive Bash. Rules in `protect_system.rules.toml`;
threshold via `CLAUDE_PROTECT_SYSTEM_LEVEL` (default `high`). No
allowlist; patterns are scoped to dangerous targets so safe paths
(`/tmp/...`, `node_modules`, `.worktrees/...`) pass naturally.

TOML authoring: use literal strings (`'...'`) for `pattern` so regex
backslashes pass through verbatim; patterns containing `'` need
triple-quoted literals (`'''...'''`).

Non-obvious scope decisions in current rules:

- `rm-system` covers `/etc`, `/usr`, `/var`, `/bin`, `/sbin`, `/lib`,
  `/boot`, `/dev`, `/proc`, `/sys`. `/var/log/...` deletions are
  collateral damage; the trade-off is keeping `rm -rf /var` blocked.
- `rm-cwd` blocks `rm .`, `rm ./`, `rm *`, `rm ./*`. Targeted globs
  (`rm *.log`) and explicit subdirs (`rm -rf ./build`) pass.
- `rm-home` only catches `~` or `$HOME` as the rm target itself;
  `rm -rf ~/.cache` is allowed.
- `kill-init` matches `kill ... 1` (PID 1 as a positional arg).
  `kill 12345` passes; `kill 1` and `kill -9 1` block.
- `kill-all` requires a signal flag _before_ the `-1` target, so
  `kill -1 12345` (SIGHUP to a real PID) passes while `kill -9 -1`
  blocks.
- `pkill-init` requires the daemon name as a whole word at end of arg,
  so `killall systemd-journald` and `pkill -f launchctl` pass.
- Cloud rules require the explicit `--auto-approve` / `--force` /
  `--recursive` / `--quiet` / `--yes` flag; interactive variants pass.

Secret-handling and git destructive ops are intentionally not
duplicated; those live in `protect_secrets.py` and
`enforce_branch_protection.py`.

### `hooks/enforce_commit_message.py` (PreToolUse)

Validates conventional-commit format before `git commit`. Gotchas:

- The imperative check (`NON_IMPERATIVE_VERBS`) is a curated denylist
  rather than algorithmic, so valid imperatives that happen to end in
  `-ed`/`-ing`/`-s` (`release`, `pass`, `address`, `feed`, `bring`)
  don't false-positive. Extend the table when a real false-negative
  escapes.
- The WIP/Draft check runs before the lowercase-first-letter check so
  `WIP add foo` produces the marker message rather than
  `subject-uppercase`.

Pass-through cases (deliberately not validated):

- `git commit` with no `-m`/`--message` (editor opens; no message to inspect).
- `--fixup` / `--squash` (git auto-generates the message).
- First line starts with a git-auto prefix (`Merge `, `Revert "`,
  `Revert '`, `fixup!`, `squash!`, `amend!`).
- Multiple `-m` args (only the first is the subject; rest is body).

### `hooks/use_uv.py` (PreToolUse)

Nudges `python`/`pip install`/`pytest`/`ruff` toward `uv run`.
Non-blocking; emits via `hookSpecificOutput.additionalContext` on
stdout (exit 0). Exit-1 + stderr would only reach the human terminal,
not the model.

## Skills

Skills are auto-loaded by Claude Code's skill router when the
description matches user intent. Conventions specific to this repo:

- Entry file must be exactly `skills/<name>/SKILL.md`. Optional
  `references/*.md` siblings for longer content the body links to.
- Description must start "Use when ..." for reliable router matching.
  Tighten triggers (file extensions, intent verbs, tool names) until
  the skill loads when it should and stays quiet when it shouldn't.
- Use `paths:` (glob) to scope auto-loading to specific file types.
- Use `disable-model-invocation: true` for framework- or
  project-specific skills that apply to a small share of work; the
  user invokes `/<name>` explicitly.

Use the `skill-creator` skill when authoring or revising a skill; do
not handcraft frontmatter from scratch.

## Commands

Slash commands live as flat markdown files at `commands/<name>.md` and
are invoked as `/<name>`. Frontmatter: `name`, `description`, optional
`argument-hint`. Body reads `$ARGUMENTS` for user-supplied input.

## Agents

Subagent definitions go at `agents/<name>.md` with frontmatter per the
Claude Code plugins reference.

## Conventions

### Hook scripts

- Python via `#!/usr/bin/env -S uv run --script` shebangs with optional
  inline metadata (`# /// script ... # ///`). Self-contained, no external
  package dependencies.
- All scripts must be executable (`chmod +x`). git tracks the mode bit;
  preserve it when copying.
- Read JSON from stdin via `json.load(sys.stdin)`. Field names are
  `tool_name`, `tool_input`, `cwd`, `transcript_path`,
  `stop_hook_active`, etc., per the hooks reference. **Not** `tool` or
  `parameters`. A hook keyed on those names silently does nothing.
- Exit code semantics:
    - `0` = allow, optionally with stdout text printed as advisory
    - `2` = block, with stderr text fed back to the model
    - other = non-blocking error, first stderr line shown in transcript
- For block decisions on Stop / PostToolUse / etc., emit
  `{"decision":"block","reason":"..."}` JSON to stdout with exit 0.

### Rule data

Rule-driven hooks use `@dataclass(frozen=True, slots=True)` holding
pattern + metadata; iteration is declaration order, first-match-wins.
Two storage shapes coexist: in-script tuples
(`enforce_branch_protection.py`, kept in Python because bypass logic
lives alongside) and sibling `<hook>.rules.toml` loaded on every
invocation via `_load_rules()` / `_load_violations()`. Load failure
exits 1 non-blocking with stderr. Keep collections flat per category;
do not introduce dispatch indirection.

### Style (applies to every component type)

- Run `ruff check`, `ruff format`, and `ty check` after editing any python file.
- `docs/` is gitignored. Spec and plan documents created during
  brainstorming and planning live there but are not committed; they
  are session-local artifacts.

## Testing

Tests are pytest-based. Run the full suite or one file:

```bash
uv run pytest
uv run pytest tests/test_branch_protection.py
```

Tests resolve hook paths via session-scoped fixtures in
`tests/conftest.py` (`hooks_dir`, plus a `repos` fixture that builds
ephemeral master/feat repos for branch-protection cases), so tests run
from any cwd. Skills and commands have no test harness here; they're
content not code.

**Always run the relevant suite before committing a change to a hook.**

To add a hook test, append a `Case(...)` to the `CASES` tuple in the
matching file. Cases are parametrized so each appears as its own
pytest item (`tests/test_x.py::test_y[case-id]`) and fails
independently.

### Safety: never run destructive commands, even in tests

The hooks in this plugin block destructive operations. Their tests and
any ad-hoc smoke checks must exercise that gate without ever putting a
real destructive command anywhere it could execute. Plan for the
worst case in both directions: **assume the hook fails to block, and
assume the command will succeed.**

Concrete rules:

- Tests feed bash strings to the hook **as data on stdin** (see the
  existing `_bash(cmd)` helpers). They never invoke the dangerous
  payload via `subprocess`, `os.system`, a shell, or any other path
  that could actually run it. A test that "verifies" a block by
  shelling out to `rm -rf ~` is one regex tweak away from wiping a
  home directory.
- Never smoke-test a hook by typing the dangerous command into a real
  Claude Code session ("let's see if it blocks `rm -rf /etc`"). If
  the hook is broken or not yet installed, the command runs. Use the
  pytest suite, which only ever passes the string to the hook as
  input.
- When validating a new pattern manually, pipe a JSON payload into
  the hook directly:

    ```bash
    echo '{"tool_name":"Bash","tool_input":{"command":"rm -rf ~"}}' \
      | plugins/natelandau-toolkit/hooks/protect_system.py
    echo "exit: $?"
    ```

    This invokes the hook script in isolation, never a shell that would
    interpret the payload. Exit `2` means the block fired.

- Cloud / IaC payloads (`terraform destroy --auto-approve`,
  `aws s3 rb --force`, `gh repo delete --yes`) are especially
  dangerous because they target real remote state. Same rule: only
  ever as a string fed to the hook, never as an executed command.
- If a test case needs a "passes through" assertion, pick a benign
  payload (`echo hello`, `ls /tmp`), not a defanged-looking
  destructive command (`rm -rf /tmp/probably-safe`). A typo or copy
  paste shouldn't be load-bearing.

## Adding components

**New hook:**

1. Drop `hooks/<your_hook>.py` in place, make it executable.
2. Register it in `hooks/hooks.json` under the matching event:
    ```json
    "<EventName>": [
      {
        "matcher": "<optional>",
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PLUGIN_ROOT}/hooks/<your_hook>.py",
            "timeout": <seconds>
          }
        ]
      }
    ]
    ```
3. Add `tests/test_<your_hook>.py` mirroring existing modules
   (parametrized `CASES` tuple, dataclass case shape, subprocess
   invocation).
4. Run `uv run pytest`, then `uv run ruff check && uv run ruff format`.

**New skill:** Invoke the `skill-creator` skill to draft frontmatter and
the "Use when ..." description, then save as
`skills/<name>/SKILL.md` (+ optional `references/*.md`).

**New command:** Create `commands/<name>.md` with frontmatter
(`name`, `description`, optional `argument-hint`) and the prompt body.
Becomes `/<name>` after reload.

**New agent:** Create `agents/<name>.md` with subagent frontmatter per
the plugins reference; dispatch via `Agent` tool with
`subagent_type=<name>`.

## Stop hook transcript shape

Field reference for hook payloads is at
<https://code.claude.com/docs/en/hooks.md>. The non-obvious bit is the
Stop transcript: `transcript_path` points at a JSONL file. Assistant
turns have `type: "assistant"` at top level; the message text is the
concatenation of `text` fields across `{"type":"text", ...}` blocks in
`message.content` (other block types like `tool_use` are interleaved
and should be skipped). Also bail early if `stop_hook_active` is true
to avoid re-fire loops.
