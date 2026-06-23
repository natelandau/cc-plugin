# CLAUDE.md

## Project overview

A Claude Code **plugin** named `natelandau-toolkit` that consolidates the
user's personal Claude Code configuration in one installable package:
PreToolUse / Stop hooks, on-demand skills, and slash commands.
Distributed as a single repository so it can be installed via Claude
Code's plugin system without hand-editing `settings.json`.

## Live documentation

This plugin tracks the live Claude Code documentation. Before authoring or
modifying any component, fetch the relevant page from the complete documentation
index at: <https://code.claude.com/docs/llms.txt> so you're working from current syntax,
fields, and semantics rather than memory:

| Topic                                              | URL                                                           |
| -------------------------------------------------- | ------------------------------------------------------------- |
| Plugin manifest, component dirs, install mechanics | <https://code.claude.com/docs/en/plugins-reference.md>        |
| Plugin authoring guide                             | <https://code.claude.com/docs/en/plugins.md>                  |
| Hook events, payloads, exit codes, matchers        | <https://code.claude.com/docs/en/hooks.md>                    |
| Hook authoring guide                               | <https://code.claude.com/docs/en/hooks-guide.md>              |
| Skill format and authoring                         | <https://code.claude.com/docs/en/skills.md>                   |
| Subagent definitions                               | <https://code.claude.com/docs/en/sub-agents.md>               |
| Slash commands                                     | <https://code.claude.com/docs/en/agent-sdk/slash-commands.md> |

Slash commands are covered in the plugins reference.

## Layout

The repo is a marketplace catalog at the root and a single plugin under
`plugins/natelandau-toolkit/`. The marketplace's `source: "./plugins/natelandau-toolkit"`
points Claude Code at the plugin directory.

```
.claude-plugin/marketplace.json                       Marketplace catalog (lists this plugin)
plugins/natelandau-toolkit/.claude-plugin/plugin.json Plugin manifest (name, description, author, version)
plugins/natelandau-toolkit/hooks/hooks.json           Event registration; references scripts via ${CLAUDE_PLUGIN_ROOT}
plugins/natelandau-toolkit/hooks/pre_tool_dispatcher.py  Unified PreToolUse entry point; routes to per-hook evaluate()
plugins/natelandau-toolkit/hooks/*.py                 Hook modules exposing evaluate(payload, cfg) + standalone __main__
plugins/natelandau-toolkit/hooks/lib/                 Shared scaffolding: io.py, config.py, registry.py, rules.py
plugins/natelandau-toolkit/skills/<name>/SKILL.md     On-demand guidance loaded by the skill router
plugins/natelandau-toolkit/skills/<name>/references/  Optional supplementary content for a skill
plugins/natelandau-toolkit/skills/shared/            Content shared by 2+ skills (no SKILL.md; linked by relative path)
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

PreToolUse hooks run through a unified dispatcher; `stop_phrase_guard`
is a separate Stop entry. Read the hook module docstrings and sibling
`.rules.toml` files for behavior; the notes below cover only
non-obvious gotchas, cross-component decisions, and design rationale.

### Hook architecture

`pre_tool_dispatcher.py` is the single PreToolUse entry point. It
loads `Config` once per invocation, then calls
`registry.applicable_checks(tool_name, cfg)` to get the ordered check
list for the incoming tool. Checks run in safety-first order;
first-block-wins. Per-check exceptions are swallowed (exit 0) so a
broken hook never wedges a tool call.

Each hook module exposes two things:

- `evaluate(payload: dict, cfg: Config) -> Decision | None` - the
  logic, callable by the dispatcher and directly from tests.
- A `__main__` block that reads stdin and exits with the right code,
  so the module can also be invoked standalone for debugging.

`stop_phrase_guard.py` is a separate Stop event entry and is not
dispatched through `pre_tool_dispatcher.py`.

### Hook configuration

Config is file-based and cascades: global file is loaded first, then
project file overrides per key. Scalar and list keys are replaced by the
project file, while `[hooks.*]` tables are deep-merged per key, so a
project file can override `[hooks.protect-system].level` without
redefining any other hook table.

- Global: `~/.claude/natelandau-toolkit.toml`
- Project: `$CLAUDE_PROJECT_DIR/.claude/natelandau-toolkit.toml`

See `hooks/natelandau-toolkit.toml.example` for the full template. Top-level keys:

| Key              | Values                          | Default    | Effect                                     |
| ---------------- | ------------------------------- | ---------- | ------------------------------------------ |
| `profile`        | `minimal`, `standard`, `strict` | `standard` | Controls which hook tier runs              |
| `disabled_hooks` | list of hook ids                | `[]`       | Force-disables hooks regardless of profile |

Profile tiers:

- `minimal` - branch-protection, protect-secrets, protect-system, stop-phrase-guard
- `standard` - above + commit-message, config-protection, use-uv
- `strict` - same as standard (reserved for future additions)

Per-hook options go under `[hooks.<hook-id>]`. Currently supported:

- `[hooks.protect-system].level` - `critical`, `high`, or `strict` (default `high`)
- `[hooks.protect-secrets].level` - `critical`, `high`, or `strict` (default `high`)

**Note:** the `CLAUDE_PROTECT_SYSTEM_LEVEL` and
`CLAUDE_PROTECT_SECRETS_LEVEL` environment variables are retired. Set
levels in the TOML config instead.

### Per-project additive rules

The four rule-driven hooks (`protect-secrets`, `protect-system`,
`stop-phrase-guard`, `config-protection`) read an optional project rules file
of the same basename as their built-in `<hook>.rules.toml`, located under:

    $CLAUDE_PROJECT_DIR/.claude/natelandau-toolkit/<hook>.rules.toml

Project rules use the same schema and array section name as the built-in file
(`[[rule]]` for `protect-secrets`/`protect-system`, `[[violation]]` for
`stop-phrase-guard`, and `protected_files`/`protected_pyproject_tables` lists
for `config-protection`) and are **additive-only**: a project may only add
blocking rules, never remove or weaken a built-in one. To turn a hook off entirely use `disabled_hooks`; to
lower a threshold use `[hooks.<id>].level`. For `protect-secrets`, an
`allowlist` in a project file is ignored (extending it would *unblock* files).

A `protect-secrets` `[[rule]]` must target a named input (`field = "file_path"`,
`command`, `content`, ...) or use `conditions`: that hook matches on named
fields and passes no primary `text`, so a bare `pattern` with no `field` never
matches. `protect-system` rules may use a bare `pattern` (matched against the
command).

A malformed project rules file **fails open**: the hook warns to stderr,
ignores that file, and keeps enforcing its built-in rules (and any project
rules that did parse). This matches how a malformed `natelandau-toolkit.toml`
is treated. A project rules file is read whenever `CLAUDE_PROJECT_DIR` is set,
with or without a `natelandau-toolkit.toml` present.

The loader lives in `lib/rules.py` (`project_rules_path`,
`load_project_rules`); `config_protection` merges via its own `_merged_rules`
because its rule data is name lists rather than `[[rule]]` tables.

### `hooks/enforce_branch_protection.py` (PreToolUse)

Blocks destructive git ops on any branch and file modifications on
`main`/`master`. A direct `git commit` is not the only way to write to a
protected branch: a `git merge`/`git pull` that creates a **merge commit**
lands on the trunk without ever running `git commit` (the merge writes the
commit itself). `creates_merge_commit` closes that gap — on a protected
branch it blocks any `git merge`/`git pull` except the forms that provably
can't write a merge commit there: `--ff-only` (fast-forward or error),
`--squash` (stages only; its follow-up `git commit` is caught by the commit
guard), `--abort`/`--quit` (cancel an in-progress merge), and `pull --rebase`
(replays, no merge commit). Merges into a non-protected branch are untouched.
Non-obvious carve-outs:

- Linked worktrees pass through, so editing inside
  `.worktrees/<branch>/` while the parent repo is on `master` works.
- In-progress squash merges allow `git commit` on a protected branch.
- `/tmp/*`-only file ops pass through.
- Gitignored targets of `Edit`/`Write`/`NotebookEdit` pass through
  (`_is_git_ignored`, via `git check-ignore`): a gitignored file is never
  committed, so editing it on `main`/`master` cannot affect tracked
  history. This covers `Edit`/`Write`/`NotebookEdit` only, not Bash
  file-mod commands. A force-tracked file that also matches an ignore
  pattern is treated as ignored here, but the separate commit guard still
  blocks committing it to the protected branch.

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
`protect_secrets.rules.toml`; threshold controlled by
`[hooks.protect-secrets].level` in the config file (default `high`).

### `hooks/protect_system.py` (PreToolUse)

Blocks system-destructive Bash. Rules in `protect_system.rules.toml`;
threshold controlled by `[hooks.protect-system].level` in the config
file (default `high`). No allowlist; patterns are scoped to dangerous
targets so safe paths (`/tmp/...`, `node_modules`, `.worktrees/...`)
pass naturally.

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

Validates conventional-commit format before `git commit` and on
`gh pr create|edit|merge` titles (the PR title/merge-subject is held to
the same rules as a commit subject). The validation core is shared; a
second detection path (`GH_PR_RE` + `GH_TITLE_VALUE_RE`) handles the
`gh pr` flags (`-t`/`--title`, and `-t`/`--subject` for merge). Gotchas:

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
- `gh pr` with no title flag (editor, `--fill`, or merge inherits the
  PR title) and non-title subcommands (`gh pr view`, `gh pr list`).
- A chained `git commit ... && gh pr ...` validates only the commit;
  the PR title is not inspected (the original `git commit` path wins).

### `hooks/config_protection.py` (PreToolUse)

Blocks `Edit`/`Write` that weaken a linter/formatter/typechecker
config, steering the agent to fix the code rather than loosen the rule
that caught it. Rule data (protected filenames + protected
`pyproject.toml` `[tool.*]` prefixes) lives in
`config_protection.rules.toml`; the diffing logic stays in Python.
Non-obvious carve-outs:

- **First-time creation passes through.** Only _modifying_ an existing
  config is blocked; bootstrapping a new one is allowed. Existence is
  probed with `lstat` (symlink-aware), per the input-hardening note
  below, so a symlink to a missing target is not read as "exists".
- **`pyproject.toml` is inspected, not blanket-blocked.** Only changes
  to a protected `[tool.<linter>]` table (`tool.ruff`, `tool.mypy`,
  `tool.ty`, ...) are blocked; dependency, build-system, project
  metadata, classifier, and test config (`[tool.pytest]`,
  `[tool.coverage]`) edits pass through so agents can still manage the
  package. For an `Edit` the `old_string -> new_string` substitution is
  applied in memory and the before/after TOML compared table-by-table;
  for a `Write` the new `content` is compared against the file on disk.
- **Fails open.** Creating `pyproject.toml` from scratch, an `Edit`
  whose `old_string` is not found, and unparsable TOML all pass: the
  hook blocks only when it can positively confirm a protected table
  changed.

No per-hook options; toggle it via the profile or `disabled_hooks`.

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
- Content shared by two or more skills lives under `skills/shared/`
  (a plain directory, no `SKILL.md`, so the router and `test_manifest`
  ignore it). Each skill's body links to it by relative path
  (`../shared/<file>.md`) and instructs the model to read it inline.
  `/pr` and `/squash` share `skills/shared/finishing-prep.md` (commit
  outstanding work, get green, update docs); `/pr` and `/cleanup-branch`
  share `skills/shared/regroup-history.md` (group commits, soft-reset +
  recommit, verify byte-identical), each caller passing its own `<base>` and
  `<original-tip>`.
- Description must start "Use when ..." for reliable router matching.
  Tighten triggers (file extensions, intent verbs, tool names) until
  the skill loads when it should and stays quiet when it shouldn't.
- Use `paths:` (glob) to scope auto-loading to specific file types.
- Use `disable-model-invocation: true` for framework- or
  project-specific skills that apply to a small share of work; the
  user invokes `/<name>` explicitly.
- A rule that must *hold* (e.g. never force-push, never weaken a linter
  config) belongs in a PreToolUse hook, not skill prose: prose is a request
  the model can stray from, a hook is enforcement. The hooks above already
  guard the destructive-git and config-weakening cases, so lean on them
  rather than restating the rule in a skill body.

Use the `skill-creator` skill when authoring or revising a skill; do
not handcraft frontmatter from scratch.

## Commands

Slash commands live as flat markdown files at `commands/<name>.md` and
are invoked as `/<name>`. Frontmatter: `name`, `description`, optional
`argument-hint`. Body reads `$ARGUMENTS` for user-supplied input.

- `/refactor` - behavior-preserving refactor (any language): multi-agent deep review by
  default, or a fast inline pass with `--quick`; see `commands/refactor.md` for phases and
  `--fix` semantics.
- `/organize` - project navigability review: a multi-agent verified pass over file/directory
  topology, naming, module boundaries, grab-bag files, and scattered functions. Advisory only
  (report + ordered reorganization plan); never moves files. See `commands/organize.md`.

## Agents

Subagent definitions go at `agents/<name>.md` with frontmatter per the
Claude Code plugins reference.

**When to reach for one — factor by isolation boundary, not by reuse.** A
subagent earns its keep only for verbose, self-contained, summarizable work
where keeping the output out of the orchestrator's context is the point (e.g.
running the full lint/test suite and returning just the failures, or a
read-only review that returns recommendations). Deduplicate shared *procedure*
with a `skills/shared/*.md` file (the `finishing-prep.md` pattern) or by one
skill invoking another — never by spinning up a subagent purely to avoid
copy-paste, and never by copy-pasting the procedure itself. Keep short,
stateful, tree-mutating steps (commit work, sync trunk) inline in the invoking
skill; they need the main conversation's context.

Current agents:

- `test-runner` - runs the project's lint/test gates, returns a `GREEN`/`RED`
  verdict with failures; does not modify files (the caller fixes). Dispatched from
  `skills/shared/finishing-prep.md` (shared by `/pr` and `/squash`) and from
  `/refactor`'s `--fix` gate.
- `doc-drift-reviewer` - read-only; compares docs against the branch diff and
  returns a prioritized drift report; recommends edits without making them.
  Dispatched from `skills/shared/finishing-prep.md`.
- `review-finder` - read-only; applies one analysis angle to a caller-provided
  scope and returns candidates in the caller's schema. Shared by `/refactor` and
  `/organize` as their parallel finders.
- `review-verifier` - read-only; judges one candidate `KEEP`/`PLAUSIBLE`/`REFUTED`
  (and, on request, behavior preservation), and defines the canonical
  verdict→label mapping the reports render. Shared by `/refactor` and `/organize`.

## Conventions

### Hook scripts

- Python via `#!/usr/bin/env -S uv run --script` shebangs with optional
  inline metadata (`# /// script ... # ///`). Stdlib only; hooks may
  import the sibling `hooks/lib/` package (`io`, `config`, `registry`,
  `rules`). No third-party dependencies.
- All scripts must be executable (`chmod +x`). git tracks the mode bit;
  preserve it when copying.
- Read JSON from stdin via `lib.io.read_payload()` (every event, Stop
  included), not a bare `json.load(sys.stdin)`. It caps the read at
  `MAX_STDIN_BYTES` and fails open to `{}` on malformed, oversized, or
  non-object input. Field names are `tool_name`, `tool_input`, `cwd`,
  `transcript_path`, `stop_hook_active`, etc., per the hooks reference.
  **Not** `tool` or `parameters`. A hook keyed on those names silently
  does nothing.
- Exit code semantics:
    - `0` = allow, optionally with stdout text printed as advisory
    - `2` = block, with stderr text fed back to the model
    - other = non-blocking error, first stderr line shown in transcript
- For block decisions on Stop / PostToolUse / etc., emit
  `{"decision":"block","reason":"..."}` JSON to stdout with exit 0.

#### Input-hardening conventions

Adopt these when authoring or extending a hook:

- **Fail open on the hook's _own_ failure.** A hook must never wedge a
  tool call because its input was unreadable or a state file was
  unwritable. The dispatcher already swallows per-check exceptions (exit
  0); `read_payload()` returns `{}` rather than raising. Preserve this.
- **Bound untrusted input.** `read_payload()` already caps stdin; any new
  hook that reads a file (transcript, state) should likewise read
  defensively rather than slurping unboundedly. The per-hook `timeout` in
  `hooks.json` is the primary guard against a runaway stream.
- **`lstat`, not `exists`, for "was this here before I touched it"
  checks.** A symlink-following `.exists()` can be fooled when the gate is
  "allow first-time creation, block modification". `config_protection`'s
  `_exists()` uses `lstat` for exactly this gate.
  `enforce_branch_protection`'s `SQUASH_MSG` check intentionally uses
  follow-symlink `.exists()` because it asks "is a squash in progress",
  which is the opposite question.
- **Quote- and combined-flag-aware matching for Bash-string rules.** A
  regex keyed on a long flag (`--message`, `--force`) silently misses the
  combined short form (`-am`, `-rf`, `-fr`). The convention, already
  followed by `enforce_commit_message` (`-[a-zA-Z]*m`) and `protect_system`
  (`(?:-\S+\s+)*`): match the bundled/reordered short-flag and zero-space
  (`-m"msg"`) forms, and carry an explicit regression case for each. Both
  hooks were audited against these forms and already cover them; extend the
  cases, not just the regex, when adding a Bash matcher.
- **Debouncing advisory output across invocations is deferred.** Re-emit
  suppression keyed on the message signature (so an ignored nudge does not
  re-fire every turn) needs per-session state, which we have deliberately
  not built (no metrics-bridge / state-file substrate yet). Until that
  lands, keep advisory hooks idempotent and cheap; do not fake debouncing
  with a per-process counter.

### Rule data

Iteration is declaration order, first-match-wins. Two storage shapes
coexist: in-script tuples (`enforce_branch_protection.py`, kept in Python
because bypass logic lives alongside) and sibling `<hook>.rules.toml`.

The TOML-driven pattern hooks (`protect_system`, `protect_secrets`,
`stop_phrase_guard`) all load through the shared `hooks/lib/rules.py`
engine rather than per-hook loaders. One `parse_rules()` validates an
`[[<section>]]` array against a caller-supplied `required` / `optional`
field set, rejecting unknown keys; `first_match()` does the
threshold-gated, first-match-wins scan. The file is parsed on every
invocation; load failure exits 1 non-blocking with stderr.

Every rule shares one canonical schema:

- `id` — slug shown in block messages (optional for hooks that don't use
  it, e.g. `stop_phrase_guard`, where it defaults to "").
- `reason` — human-facing explanation (the Stop hook used to call this
  `correction`; it is now `reason` like the others).
- `level` — optional threshold tier (`critical` < `high` < `strict`);
  omit it for hooks without a threshold. `rules.LEVELS` is the one source
  of truth for the ordering.
- exactly one matcher: a single `pattern` **or** a `conditions` array.
    - `pattern` is a regex matched against the hook's primary `text` by
      default, or against `fields[field]` when the rule sets an optional
      `field` key. `field` lets one rule list mix rules targeting different
      named inputs without per-tool branching: `protect_secrets` is one
      `[[rule]]` list where each rule sets `field = "file_path"` or
      `field = "command"`, and a file_path rule simply can't match a Bash
      call (empty `file_path`). `field` is invalid alongside `conditions`.
    - `conditions` is an array of `{field, operator, pattern}`, AND-combined,
      so a rule can require several named fields at once (e.g. a `file_path`
      pattern and a `content` substring) without new Python. Operators:
      `regex_match`, `contains`, `not_contains`, `equals`, `starts_with`,
      `ends_with`; the non-regex operators are case-insensitive, matching
      the `re.IGNORECASE` convention.

Both `field` and `conditions` resolve names against a `fields` dict the
hook passes to `first_match`. Every hook exposes its inputs as named fields
(`protect_secrets._match_fields`: file_path, command, content, old_string,
new_string, tool_name; `protect_system`: command, tool_name;
`stop_phrase_guard`: message), so a rule can target any of them. Hooks also
pass a primary `text`, which an unqualified `pattern` rule matches.

All patterns compile at load time so a bad regex surfaces as a load error,
not in the hot path. Keep collections flat per category; do not introduce
dispatch indirection. `lib/rules.py` is covered by `tests/test_lib_rules.py`
(the engine) plus each hook's own characterization tests (the wiring).

### Style (applies to every component type)

- Run `ruff check`, `ruff format`, and `ty check` after editing any python file.
- Ruff targets `py314` (matching `requires-python`), so `ruff format`
  drops the parentheses around multi-exception `except` clauses per
  PEP 758: `except (A, B):` becomes `except A, B:`. This is valid,
  intentional Python 3.14 syntax, not the Python 2 `except E, name:`
  bug it resembles. Do not "fix" it back to parentheses; ruff will just
  strip them again on the next format.
- `docs/` is gitignored. Spec and plan documents created during
  brainstorming and planning live there but are not committed; they
  are session-local artifacts.
- Don't cross-reference sibling skills or commands inside a skill/command
  _body_. The reader is an agent executing that one component, often in an
  unrelated project; naming a component it won't invoke (`/squash`, `/pr`,
  another skill) is noise. State the behavior or boundary directly instead.
  Two carve-outs: hooks the component actually trips (e.g.
  `enforce_commit_message`) are fair game because they describe enforcement
  the agent hits, and cross-references in _this_ file (the maintainer's
  catalog) are fine.

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

**New PreToolUse hook (dispatcher-routed, most common):**

1. Write `hooks/<your_hook>.py` exposing `evaluate(payload, cfg) ->
Decision | None` and a `__main__` block. Make it executable. If the hook is
rule-driven, load project rules via `rules.load_project_rules(RULES_FILE.name, ...)` and concatenate them with the built-in rules.
2. Add it to `HOOK_PROFILES` (which profiles it runs in) and
   `PRE_TOOL_CHECKS` (which tool names it matches) in `hooks/lib/registry.py`.
3. Add `tests/test_<your_hook>.py` with:
    - Per-check cases that call `evaluate()` directly or via subprocess.
    - At least one dispatcher-level case that exercises the full
      `pre_tool_dispatcher.py` path.
4. Add the hook id to `DISPATCHER_INVOKED` in `tests/test_manifest.py`
   so the orphan-guard passes.
5. Run `uv run pytest`, then `uv run ruff check && uv run ruff format`.

**New hook for a different event (Stop, PostToolUse, etc.):**

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

**New agent:** Create `agents/<name>.md` with subagent frontmatter
(`name`, `description`, optional `tools`/`disallowedTools`/`model`; `name` must
equal the file stem). Restrict a read-only agent with a `tools` allowlist.
Dispatch via `Agent` tool with `subagent_type=<name>`. `test_manifest` validates
the frontmatter automatically; run `uv run pytest`.

## Stop hook transcript shape

Field reference for hook payloads is at
<https://code.claude.com/docs/en/hooks.md>. The non-obvious bit is the
Stop transcript: `transcript_path` points at a JSONL file. Assistant
turns have `type: "assistant"` at top level; the message text is the
concatenation of `text` fields across `{"type":"text", ...}` blocks in
`message.content` (other block types like `tool_use` are interleaved
and should be skipped). Also bail early if `stop_hook_active` is true
to avoid re-fire loops.
