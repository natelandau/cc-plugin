# CLAUDE.md

A Claude Code **marketplace** repo shipping one plugin, `natelandau-toolkit`, under
`plugins/natelandau-toolkit/`. The marketplace layout stays because it is the install
path, not because a second plugin is planned.

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

## Hook code

- **Live docs drift.** Before authoring or modifying a hook/skill/command/agent, fetch
  the current page from <https://code.claude.com/docs/llms.txt> (plugins-reference,
  hooks, skills, sub-agents). Don't work from memory.
- **`${CLAUDE_PLUGIN_ROOT}`** prefixes every path in `hooks.json`; the plugin dir moves
  on install.
- **Entry scripts vs modules.** Only the stage dispatchers (`hooks/<stage>.py`) carry
  the `uv run --script` shebang and PEP 723 block and are `100755`. Everything they
  import, stage plugins included, has neither and stays `100644`.
- **Stdlib only** in hook code.
- **Read stdin via `io.read_payload()`**, not bare `json.load`. Payload fields are
  `tool_name`, `tool_input`, `cwd`, `transcript_path`, `stop_hook_active`, **not**
  `tool`/`parameters` (a hook keyed on those silently no-ops).
- **Exit codes:** `0` = allow (stdout = advisory), `2` = block (stderr fed to the
  model). For Stop/PostToolUse a block is `{"decision":"block","reason":"..."}` on
  stdout with exit 0.
- **Fail open** on the hook's own failure. Use `lstat`, not `exists`, for "was this
  here before I touched it" gates.
- **Stop payload has no assistant text.** Read `event["assistant_message"]`, which
  the dispatcher's `prepare` (`transcript.parse_stop`) adds.
- **Bash matching:** a regex on `--message`/`--force` misses `-am`, `-rf`, `-fr`, and
  `-m"msg"`. Match bundled and reordered short forms, with a regression case for each.
- **Rule TOML:** use literal strings (`'...'`) for `pattern`.
- **ruff targets `py314`**, so `ruff format` rewrites `except (A, B):` as
  `except A, B:` (PEP 758). Don't revert it.

## Config invariants

- A project config layer may only **tighten** safety. `exempt_paths` and
  `trusted_remote_hosts` are read from the global layer alone, because the project
  file is committed inside the repo the guard protects. A safety list option goes in
  `config.ADDITIVE_OPTIONS` so layers union it. Style options such as
  `[hooks.commit-message]` may be loosened.
- Users own all configuration; nothing configurable lives in the plugin dir, which is
  replaced on update.
- Run every command-extracted path through `lib.paths.expand_user`: the hook sees the
  command before the shell expands `~`.
- Subprocess tests pin `HOME` to the `empty_home` fixture, so a developer's global
  config cannot decide the outcome.

## Skills, commands, agents

- Author or revise a skill with the `skill-creator` skill. The entry file is
  `skills/<name>/SKILL.md` and its description starts "Use when …".
- Don't cross-reference sibling skills or commands inside a component body. Its
  reader is an agent running that one component, often in an unrelated project.
- A rule that must **hold** belongs in a PreToolUse hook, not skill prose.

## Safety: never run destructive commands, even in tests

Assume the hook fails to block **and** the command succeeds.

- Feed bash strings to the hook **as data on stdin**, never through
  `subprocess`/`os.system`/a shell. Cloud and IaC payloads (`terraform destroy`,
  `gh repo delete`) target real remote state: same rule.
- Validate a pattern by piping a payload in, never by typing it in a real session:

  ```bash
  echo '{"tool_name":"Bash","tool_input":{"command":"rm -rf ~"}}' \
    | plugins/natelandau-toolkit/hooks/pretooluse.py   # exit 2 = blocked
  ```

- "Passes through" assertions use a benign payload (`echo hello`).
