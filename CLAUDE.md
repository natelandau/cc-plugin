# CLAUDE.md

Marketplace of plugins under `plugins/`: `natelandau-toolkit` (all hooks, general
skills, shared agents), `natelandau-git`, and one `natelandau-[stack]` per stack.
Prefix every plugin name with `natelandau-`, because the manifest name is the namespace
for its components. Add each plugin's `plugin.json` to commitizen `version_files`,
because all plugins share one version.

[CONTRIBUTING.md](CONTRIBUTING.md) covers the layout, the dispatcher model, the plugin
contract, and step-by-step recipes. Per-hook behavior lives in each module's docstring
and sibling `<hook>.rules.toml`; config semantics live in `hooks/lib/config.py`.

## Gates

```bash
uv run duty lint     # ruff, format check, ty, vulture, typos, yamllint, shellcheck, prek hooks
uv run duty test     # full suite; extra args go to pytest
uv run ruff format . # apply formatting (duty format only checks)
```

`ty` is the sole typechecker; ignore Pyright. Skills, commands, and agents are content
with no test harness. Run the gates before committing a code change.

- Run checks only through these duties, never the bare tool (`pytest`, `ruff check`).
  Each gate runs through gate-cache, and a direct run skips its shared pass records.
  The one exception: `uv run ruff format .` to apply formatting, which no duty does.
- Run `gate-cache --skill` before adding or changing a gate in `duties.py`. A scoped
  gate (`PY_GATE_PATHS`, `TEST_GATE_PATHS`) must list every tracked file it reads.

## Hook code

- Prefix every path in `hooks.json` with `"${CLAUDE_PLUGIN_ROOT}"` (quoted); the
  plugin dir moves on install and its path can contain a space.
- Only the stage dispatchers (`hooks/<stage>.py`) carry the `uv run --script` shebang
  and PEP 723 block and are `100755`. Everything they import, stage plugins included,
  has neither and stays `100644`.
- Hook code is stdlib only.
- Read stdin via `io.read_payload()`, not bare `json.load`. Payload fields are
  `tool_name`, `tool_input`, `cwd`, `transcript_path`, `stop_hook_active`, not
  `tool`/`parameters` (a hook keyed on those silently no-ops).
- Exit codes: `0` = allow (stdout = advisory), `2` = block (stderr fed to the model).
  For Stop/PostToolUse a block is `{"decision":"block","reason":"..."}` on stdout with
  exit 0.
- Fail open when the hook itself fails. Use `lstat`, not `exists`, for "was this here
  before I touched it" gates.
- The Stop payload has no assistant text. Read `event["assistant_message"]`, which the
  dispatcher's `prepare` (`transcript.parse_stop`) adds.
- A Bash regex on `--message`/`--force` misses `-am`, `-rf`, `-fr`, and `-m"msg"`.
  Match bundled and reordered short forms, with a regression case for each.
- Rule TOML: use literal strings (`'...'`) for `pattern`.
- ruff targets `py314`, so `ruff format` rewrites `except (A, B):` as `except A, B:`
  (PEP 758). Don't revert it.

## Config invariants

- A project config layer can only tighten safety. `exempt_paths` and
  `trusted_remote_hosts` are read from the global layer alone, because the project
  file is committed inside the repo the guard protects. A safety list option goes in
  `config.ADDITIVE_OPTIONS` so layers union it. Style options such as
  `[hooks.commit-message]` can be loosened.
- Put nothing configurable in the plugin dir; updates replace it. Users own all
  configuration.
- Run every command-extracted path through `lib.paths.expand_user`: the hook sees the
  command before the shell expands `~`.
- Subprocess tests pin `HOME` to the `empty_home` fixture, so a developer's global
  config cannot decide the outcome.

## Skills, commands, agents

- Before writing or changing a hook, skill, command, or agent, fetch the current page
  (plugins-reference, hooks, skills, sub-agents) from
  <https://code.claude.com/docs/llms.txt> instead of working from memory.
- Write or revise a skill, command, agent, or CLAUDE.md with the
  `natelandau-toolkit:prompt-writer` skill.
- A skill's entry file is `skills/<name>/SKILL.md`; its folder name must match its
  `name` field, and its description starts "Use when ...".
- Skills reference bundled scripts through `${CLAUDE_SKILL_DIR}`, not
  `CLAUDE_PLUGIN_ROOT`.
- Every model-invocable skill or command costs context in every session with its
  plugin. Run-on-request components get `disable-model-invocation: true`; agent
  descriptions stay one line naming who dispatches them.
- A skill reads `../shared/` only within its own plugin. A cross-plugin agent is
  named with its prefix (`natelandau-toolkit:test-runner`) and its plugin is listed
  in `dependencies`.
- A rule that must hold every time belongs in a PreToolUse hook, not skill prose.

## Safety: never run destructive commands, even in tests

Assume the hook fails to block and the command succeeds.

- Feed bash strings to the hook as data on stdin, never through
  `subprocess`/`os.system`/a shell. Cloud and IaC payloads (`terraform destroy`,
  `gh repo delete`) target real remote state: same rule.
- Validate a pattern by piping a payload in, never by typing it in a real session:

  ```bash
  echo '{"tool_name":"Bash","tool_input":{"command":"rm -rf ~"}}' \
    | plugins/natelandau-toolkit/hooks/pretooluse.py   # exit 2 = blocked
  ```

- "Passes through" assertions use a benign payload (`echo hello`).
