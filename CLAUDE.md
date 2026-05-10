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

Slash commands are covered under the plugins reference. Always prefer the
live docs over training-data recall: fields and semantics evolve.

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
plugins/natelandau-toolkit/agents/<name>.md           Subagent definitions (currently empty)
tests/test_*.py                                       Hook characterization test harnesses (no pytest dep)
```

`${CLAUDE_PLUGIN_ROOT}` resolves to the installed `plugins/natelandau-toolkit/`
directory, so plugin-internal references like `${CLAUDE_PLUGIN_ROOT}/hooks/foo.py`
are written relative to the plugin root, not the repo root.

When users enable this plugin, Claude Code clones the repo into
`~/.claude/plugins/...`, sets the `CLAUDE_PLUGIN_ROOT` environment
variable to that cloned path, and loads each component declared in
the manifest and component dirs. Hook commands in `hooks/hooks.json`
and any other path-bearing config should reference scripts via
`${CLAUDE_PLUGIN_ROOT}/...` so they resolve correctly regardless of
install location.

## Hooks

### `hooks/enforce_branch_protection.py` (PreToolUse)

Blocks two classes of action:

1. **Destructive git commands** on every branch: force push (flag or
   `+refspec` form), `reset --hard`, `clean -f`, `checkout .`, `restore .`,
   `rebase --no-verify`, `branch -D main|master`.
2. **File modifications on protected branches** (`main`, `master`):
   `Edit`/`Write`/`NotebookEdit` tools, plus bash file mutators (`rm`, `mv`,
   `sed -i`, `tee`, `>` and `>>` redirects, etc.). Pure git read commands
   pass through. `/tmp/*`-only file ops pass through. Linked worktrees pass
   through (so editing inside `.worktrees/<branch>/` while the parent repo
   is on master is fine). In-progress squash merges allow `git commit`.

Rule data lives in two flat tuples (`DESTRUCTIVE_RULES`,
`PROTECTED_FILE_MOD_RULES`) of `Rule` dataclasses. To add a rule, append
to the appropriate tuple. See the `Rule` docstring for field semantics.

### `hooks/stop_phrase_guard.py` (Stop)

Reads the most recent assistant text turn from `transcript_path` (the JSONL
session log Claude Code passes to Stop hooks), runs it against a list of
violation patterns derived from CLAUDE.md golden rules ("ownership dodging",
"known limitation dodging", "permission-seeking mid-task"), and on the
first match emits `{"decision":"block","reason":"STOP HOOK VIOLATION: ..."}`
to stdout. Claude Code reads the decision and forces the assistant to keep
working with the correction as next instruction.

**Critical gotcha:** Stop hook input does NOT provide a `last_assistant_message`
field. The official `hookify` plugin reads `transcript_path` and so does
this hook. If you ever see code reaching for `last_assistant_message`, it's
broken and exits 0 silently.

Patterns live in a `Violation` dataclass tuple. They are case-insensitive
regex; first match wins. Patterns are deliberately a mix of ownership-dodging
and permission-seeking phrases the user has decided are unwanted. Be cautious
about adding broad patterns (`getting long`, `next session`) since they
false-positive in legitimate contexts.

### `hooks/protect_secrets.py` (PreToolUse)

Blocks attempts to read, edit, write, or exfiltrate sensitive files via
the `Read`/`Edit`/`Write`/`Bash` tools. Two flat tuples of `Rule`
dataclasses drive matching:

- `SENSITIVE_FILES` -- regexes tested against `tool_input.file_path` for
  Read/Edit/Write. Catches `.env`, SSH private keys, AWS/GCloud/Azure
  credentials, PEM/key/keystore files, etc.
- `BASH_PATTERNS` -- regexes tested against the full bash command string.
  Catches direct reads (`cat .env`), env dumps (`printenv`,
  `echo $SECRET_KEY`), exfiltration (`scp .env`, `curl -d @.env`), and
  destructive ops on secret files (`rm .env`, `cp id_rsa`).

Each rule has a `level`: `critical`, `high`, or `strict`. The active
threshold is read from `CLAUDE_PROTECT_SECRETS_LEVEL` (default `high`)
and rules above the threshold are skipped. An `ALLOWLIST` of template
patterns (`.env.example`, `env.sample`, etc.) short-circuits both file
and bash checks before any rule fires.

Ported from karanb192/claude-code-hooks `protect-secrets.js`. Differences
from the source: this version uses the repo's `exit 2 + stderr` block
convention instead of the JS hook's `permissionDecision: deny` JSON, and
omits the `~/.claude/hooks-logs/` log writer to match other hooks here.

### `hooks/enforce_commit_message.py` (PreToolUse)

Validates conventional commit format before `git commit` runs. Inspects
the bash command for `git commit` invocations carrying `-m`/`--message`,
extracts the first message value (handling simple quoting and the
`"$(cat <<TAG ... TAG)"` heredoc form this codebase uses for multi-line
commits), and checks the first non-empty line against the rules in the
`git-rules` skill: header <=70 chars, `<type>(<scope>)!?: <subject>`
grammar with type in a fixed allowlist (`build`, `ci`, `docs`, `feat`,
`fix`, `perf`, `refactor`, `style`, `test`), optional `!` breaking-change
marker, lowercase first letter of subject, no trailing whitespace,
period, `!`, or `?`, no leading WIP/Draft marker, and an imperative-mood
first word.

The imperative check is a curated denylist (`NON_IMPERATIVE_VERBS`) that
maps known past-tense, gerund, and third-person-singular forms to their
imperative root for the suggestion in the block message. Curated rather
than algorithmic so we never block valid imperatives that happen to end
in `-ed`/`-ing`/`-s` (`release`, `pass`, `address`, `feed`, `bring`).
Extend the table when a real false-negative escapes.

The WIP/Draft check (`WIP_MARKER_RE`) catches `wip`, `[wip]`, `draft`,
`[draft]`, and `(draft)` at the start of the subject, case-insensitive.
It runs before the lowercase-first-letter check so `WIP add foo`
produces the more specific marker message rather than `subject-uppercase`.
Pattern ported from `crate-ci/committed`.

Pass-through cases:

- `git commit` with no `-m`/`--message`. The editor opens; we have no
  message to inspect.
- `--fixup` / `--squash` flags. Git auto-generates the message.
- Messages whose first line begins with a git-auto-generated prefix
  (`Merge `, `Revert "`, `Revert '`, `fixup!`, `squash!`, `amend!`).
- Multiple `-m` args. Only the first is the subject; subsequent args
  are body paragraphs which the project conventions do not constrain.

The `GIT_COMMIT_RE` is not anchored to a command-start position, so a
literal `git commit` substring inside an echoed string can false-positive.
In practice agents execute commits rather than echo them, and the cost of
a spurious block is just retyping the message.

### `hooks/use_uv.py` (PreToolUse)

Lightweight nudge: detects bash invocations of `python `, `pip install`,
`pytest`, or `ruff` and emits a `hookSpecificOutput.additionalContext` JSON
payload on stdout (exit 0). Claude Code injects that context into the
model's next turn so the model actually sees the nudge and switches to
`uv run`. The previous version used exit 1 with stderr, which per the
hooks spec only reaches the human terminal, so it never nudged Claude.

## Skills

Skills are auto-loaded by Claude Code's skill router whenever the
description matches user intent. Layout:

- `skills/<name>/SKILL.md` is the entry file (filename must be exactly `SKILL.md`).
- Optional `skills/<name>/references/*.md` for supplementary content the
  skill body can link to.
- Required frontmatter fields are `name` and `description`. The
  optional `argument-hint` field is also recognized (the ported `gha`
  skill uses it).
- The optional `paths:` field (glob string or YAML list) scopes
  auto-loading to matching files, e.g. `paths: "**/*.py"` on
  `python-standards`. Use it when a skill is tied to a specific file
  type so the router triggers on file edits, not just intent
  matching. Documented at <https://code.claude.com/docs/en/skills.md>.
- The optional `disable-model-invocation: true` field opts a skill out
  of the router entirely. Its description never loads into the skill
  listing and the user must invoke `/<name>` explicitly. Use it for
  framework- or project-specific skills that apply to a small share
  of work (currently `daisyui`, `flask-development`,
  `gha`, `htmx-expert`, `tortoise-orm`).
- Description must read "Use when ..." so the router can match it. The
  more specific the trigger conditions (file extensions, intent verbs,
  tool names), the more reliably it loads.

Use the `skill-creator` skill (already on the user's machine) when authoring
or revising a skill. Do not handcraft frontmatter from scratch.

The four "rule-derived" skills (`python-standards`, `bash-standards`,
`git-rules`, `inline-comments`) replace what used to be `@`-imported rule
fragments in the user's global `~/.claude/CLAUDE.md`. They switch from
always-on to on-demand routing; if a rule isn't triggering when it
should, tighten the description.

## Commands

Slash commands live as flat markdown files at `commands/<name>.md`.
The filename (without `.md`) is the command name; `commands/foo.md` is
invoked as `/foo`. Frontmatter supports `description` and the optional
`argument-hint`. Note that `create-prd.md` uses a non-standard
`arguments:` field; it works because the body reads `$ARGUMENTS` directly,
but is not the documented field name.

The other shipped command, `transfer-context.md`, predates the
convention and has no frontmatter at all. It still works because
Claude Code falls back to filename for the command name. New
commands should include the frontmatter.

## Agents

Subagent definitions go at `agents/<name>.md` with frontmatter as
described in the Claude Code plugins reference. Currently empty.

## Conventions

### Hook scripts

- Python via `#!/usr/bin/env -S uv run --script` shebangs with optional
  inline metadata (`# /// script ... # ///`). Self-contained, no external
  package dependencies.
- All scripts must be executable (`chmod +x`). git tracks the mode bit;
  preserve it when copying.
- Read JSON from stdin via `json.load(sys.stdin)`. Field names per the
  Claude Code hooks reference: `tool_name`, `tool_input`, `cwd`,
  `transcript_path`, `stop_hook_active`, etc. **Not** `tool` or
  `parameters`, those are wrong (a previous version of `use_uv.py`
  used them and silently did nothing).
- Exit code semantics:
    - `0` = allow, optionally with stdout text printed as advisory
    - `2` = block, with stderr text fed back to the model
    - other = non-blocking error, first stderr line shown in transcript
- For block decisions on Stop / PostToolUse / etc., emit
  `{"decision":"block","reason":"..."}` JSON to stdout with exit 0.

### Rule data

Both rule-driven hooks (`enforce_branch_protection.py`,
`stop_phrase_guard.py`) use the same shape: a `@dataclass(frozen=True, slots=True)`
holding the pattern + metadata, then a tuple of instances. Iteration is
in declaration order; first match wins. Don't introduce a `RuleCategory`
enum or other dispatch indirection, flat tuples per category are simpler.

### Style (applies to every component type)

- Run `ruff check`, `ruff format`, and `ty check` after editing any python file.
- No em-dashes anywhere (in comments, docstrings, correction strings,
  SKILL.md bodies, or CLAUDE.md). Use commas, periods, regular hyphens,
  or rewrite.
- Comments explain _why_, not _what_. Don't paraphrase the code.
- Skill descriptions follow "Use when ..." phrasing for reliable routing.
- `docs/` is gitignored. Spec and plan documents created during
  brainstorming and planning live there but are not committed; they
  are session-local artifacts.

## Testing

Tests are pytest-based. Run the full suite or one file:

```bash
uv run pytest
uv run pytest tests/test_branch_protection.py
```

Hook paths resolve via the session-scoped `hooks_dir` fixture in
`tests/conftest.py`, so tests run from any cwd. The same conftest
defines a session-scoped `repos` fixture that builds two ephemeral git
repos (master, feat) plus a non-repo dir, reused across all
branch_protection cases. `test_stop_phrase_guard.py` uses pytest's
built-in `tmp_path` for per-test transcript files.

**Always run the relevant suite before committing a change to a hook.** The
test infrastructure is the safety net for behavior preservation across
refactors. Skills and commands have no test harness convention here, they
are content not code.

To add a hook test, append a `Case(...)` to the `CASES` tuple in the
relevant file. Cases are parametrized via `@pytest.mark.parametrize`,
keyed by the `id` field, so each case shows up as its own pytest item
(`tests/test_x.py::test_y[case-id]`) and fails independently.

## Adding a new hook

1. Drop `plugins/natelandau-toolkit/hooks/<your_hook>.py` in place. Make it executable.
2. Register it in `plugins/natelandau-toolkit/hooks/hooks.json` under the matching event:
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
3. Add `tests/test_<your_hook>.py` mirroring the existing pytest modules
   (parametrized `CASES` tuple, dataclass case shape, subprocess-based
   invocation of the hook script).
4. Run `uv run pytest`, then `uv run ruff check && uv run ruff format`.

## Adding a new skill

1. Invoke the `skill-creator` skill to draft the skill, including
   frontmatter and "Use when ..." description.
2. Save it as `plugins/natelandau-toolkit/skills/<name>/SKILL.md`. Add
   `plugins/natelandau-toolkit/skills/<name>/references/*.md` for any longer
   supplementary content.
3. Restart Claude Code or reload skills so the router picks up the new
   entry.

## Adding a new command

1. Create `plugins/natelandau-toolkit/commands/<name>.md` with frontmatter
   (`description`, optional `argument-hint`) and the command body. The body
   is the prompt the command sends when invoked.
2. The command becomes available as `/<name>` after Claude Code reloads.

## Adding a new agent

1. Create `plugins/natelandau-toolkit/agents/<name>.md` with subagent
   frontmatter per the Claude Code plugins reference.
2. Reference and dispatch via the `Agent` tool with `subagent_type=<name>`.

## Hook input/output reference

Authoritative source: <https://code.claude.com/docs/en/hooks.md>. Key fields
this plugin actually uses:

| Field              | Events     | Notes                                                                                    |
| ------------------ | ---------- | ---------------------------------------------------------------------------------------- |
| `tool_name`        | PreToolUse | `Bash`, `Edit`, `Write`, `NotebookEdit`, `Read`, etc.                                    |
| `tool_input`       | PreToolUse | Tool-specific; e.g. `{"command": "..."}` for Bash, `{"file_path": "..."}` for Edit/Write |
| `cwd`              | all        | Session working directory                                                                |
| `transcript_path`  | Stop       | Path to JSONL session transcript; tail it for the last assistant turn                    |
| `stop_hook_active` | Stop       | True if the Stop hook already fired this turn; bail to avoid loops                       |

JSONL transcript entries use:

- `type: "assistant"` at top level for assistant turns
- `message.content` is a list of blocks, each `{"type": "text", "text": "..."}` or `{"type": "tool_use", ...}`
- Concatenate the `text` fields of `text`-typed blocks to get the full message text
