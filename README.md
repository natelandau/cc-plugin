# natelandau-toolkit

A personal Claude Code plugin that bundles my hooks, skills, and slash
commands into a single installable package.

> **Personal use only.** This plugin is published openly so it can be
> installed by Claude Code, but it is tuned to one developer's workflow,
> opinions, and habits. It is not a general-purpose toolkit. The hooks
> enforce rules that may surprise you, the skills assume specific tooling
> (uv, ruff, ty, pytest), and the stop-phrase guard reflects personal
> preferences about how Claude should communicate. Fork it if any of that
> is useful, but don't expect support, backwards compatibility, or
> stability.

## What's inside

- **Hooks** that block destructive git commands, protect `main`/`master`
  from edits, nudge Claude toward `uv run`, and stop the assistant from
  emitting specific phrases.
- **Skills** for Python, Bash, git, inline comments, refactoring, and
  documentation writing. Framework-specific skills (Flask, htmx,
  daisyUI, Beanie ODM, Tortoise ORM, GitHub Actions triage) are
  manual-only, invoked with `/<skill-name>`.
- **Slash commands**, currently just `/create-prd` for turning
  conversation context into a Product Requirements Document.

## Requirements

- Claude Code with plugin support
- Python 3.12 or newer (for running and testing the hook scripts)
- [uv](https://docs.astral.sh/uv/) for dependency and script management
- Git

## Installation

This is a Claude Code plugin, so install it through Claude Code itself
rather than copying files into `~/.claude/`. Run these commands inside
Claude Code:

1. Add this repository as a marketplace:

   ```
   /plugin marketplace add natelandau/cc-plugin
   ```

2. Install the plugin from that marketplace:

   ```
   /plugin install natelandau-toolkit@natelandau-cc-plugin
   ```

3. Reload plugins so the hooks, skills, and commands activate without
   restarting:

   ```
   /reload-plugins
   ```

The plugin installs to user scope by default, so it's available across
all your projects. To pick a different scope or browse interactively,
run `/plugin` and use the **Discover** and **Installed** tabs.

### Managing the plugin later

Use these commands to disable, re-enable, or remove the plugin without
touching the marketplace:

```
/plugin disable natelandau-toolkit@natelandau-cc-plugin
/plugin enable natelandau-toolkit@natelandau-cc-plugin
/plugin uninstall natelandau-toolkit@natelandau-cc-plugin
```

To refresh the marketplace after upstream changes, run
`/plugin marketplace update natelandau-cc-plugin`. To remove the
marketplace entirely (which also uninstalls the plugin), run
`/plugin marketplace remove natelandau-cc-plugin`.

### How install paths resolve

When the plugin is enabled, Claude Code clones the repo into
`~/.claude/plugins/...` and sets `CLAUDE_PLUGIN_ROOT` to that path. All
hook commands in `hooks/hooks.json` reference scripts via
`${CLAUDE_PLUGIN_ROOT}/...` so they resolve correctly regardless of
install location.

## Development

Clone the repo and install the dev dependencies with uv:

```bash
git clone <this-repo> cc-plugin
cd cc-plugin
uv sync
```

### Running tests

The hooks have a pytest suite. Run the full suite or a single file:

```bash
uv run pytest
uv run pytest tests/test_branch_protection.py
```

Hook paths resolve through a session-scoped fixture in
`tests/conftest.py`, so tests run from any cwd.

### Linting and formatting

```bash
uv run ruff check
uv run ruff format
uv run ty check
```

These run automatically via `prek` (the dev pre-commit runner) on
commit, but you can run them manually too.

### Project layout

```
.claude-plugin/marketplace.json                       Marketplace catalog
plugins/natelandau-toolkit/.claude-plugin/plugin.json Plugin manifest
plugins/natelandau-toolkit/hooks/hooks.json           Event registration
plugins/natelandau-toolkit/hooks/*.py                 Hook scripts (uv run --script)
plugins/natelandau-toolkit/skills/<name>/SKILL.md     On-demand skill content
plugins/natelandau-toolkit/commands/<name>.md         Slash commands
plugins/natelandau-toolkit/agents/<name>.md           Subagent definitions (currently empty)
tests/test_*.py                                       Pytest suite for the hooks
```

### Adding a hook, skill, or command

`CLAUDE.md` documents the conventions for each component type, including
the exit-code semantics for hooks, the required frontmatter fields for
skills, and the pytest case structure used in `tests/`. Read it before
adding anything new.

## License

Released under the [MIT License](LICENSE). The license is permissive,
but the personal-use caveat above still applies in spirit: you're
welcome to fork or borrow code, just don't expect this repo to behave
like a maintained product.
