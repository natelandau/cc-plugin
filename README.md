# natelandau-toolkit

A personal Claude Code plugin bundling one developer's hooks, skills, and
slash commands into a single installable package.

> **Personal use only.** This plugin is published openly so Claude Code can
> install it, but it's tuned to one person's workflow and tooling (uv, ruff,
> ty, pytest). The hooks enforce opinionated rules and the stop-phrase guard
> reflects personal preferences. Fork what's useful, but expect no support,
> stability, or backwards compatibility.

## What's inside

The plugin ships three kinds of component: hooks that run automatically, skills
Claude loads when relevant, and slash commands you invoke by name.

### Hooks

Hooks run automatically on Claude's tool calls. Most block a risky action and
explain why; the uv nudge is advisory. See [Configuration](#configuration) to
tune or disable them.

- Branch protection blocks destructive git operations and edits to
  `main`/`master`.
- Secret protection blocks reading, editing, or exfiltrating sensitive files.
- System protection blocks system-destructive shell commands.
- Commit-message validation holds `git commit` and `gh pr` titles to
  conventional-commit format.
- The uv nudge suggests `uv run` when it sees a bare `python`, `pip`, `pytest`,
  or `ruff` call.
- The stop-phrase guard stops Claude from ending a turn with certain filler
  phrases.

### Skills Claude loads on its own

Claude pulls these in when the task matches, no action needed:

- `documentation-writer` for writing and editing user-facing docs.
- `python-refactor` for restructuring Python without changing behavior.
- `flask-development` for building Flask 3+ apps.
- `htmx-expert` for writing and debugging htmx.
- `nclutils` for code that uses the `nclutils` library.
- `tufte-viz` for critiquing data visualizations against Tufte's principles.

### Slash commands you invoke

Type these yourself when you want them:

- `/pr` commits outstanding work, runs the tests, pushes the branch, and opens
  a pull request.
- `/squash` collapses a finished branch into one commit on `main`, then cleans
  up the branch.
- `/gha` investigates a GitHub Actions failure and suggests a fix.
- `/create-prd` turns the conversation into a Product Requirements Document.
- `/daisyui` for building UIs with daisyUI v5 and Tailwind.
- `/tortoise-orm` for building apps with Tortoise ORM.

## Requirements

- Claude Code with plugin support
- [uv](https://docs.astral.sh/uv/), which runs the hook scripts and provisions
  the Python version each one needs
- Git

## Installation

Install through Claude Code rather than copying files into `~/.claude/`. Run
these inside Claude Code:

1. Add this repository as a marketplace:

   ```
   /plugin marketplace add natelandau/cc-plugin
   ```

2. Install the plugin:

   ```
   /plugin install natelandau-toolkit@natelandau-cc-plugin
   ```

3. Reload so the hooks, skills, and commands activate without a restart:

   ```
   /reload-plugins
   ```

The plugin installs to user scope, so it's available across all your projects.
To pick a different scope or browse interactively, run `/plugin` and use the
**Discover** and **Installed** tabs.

To disable, re-enable, or remove it later:

```
/plugin disable natelandau-toolkit@natelandau-cc-plugin
/plugin enable natelandau-toolkit@natelandau-cc-plugin
/plugin uninstall natelandau-toolkit@natelandau-cc-plugin
```

## Configuration

The hooks work without any setup. To change which hooks run or how strict they
are, add a config file. Settings load from two locations, and the project file
overrides the global one key by key:

- Global: `~/.claude/natelandau-toolkit.toml`
- Per-project: `<project>/.claude/natelandau-toolkit.toml`

Copy `plugins/natelandau-toolkit/hooks/natelandau-toolkit.toml.example` to
either path and edit it. Every key is optional, and an absent file uses the
defaults below.

### Pick a profile

The `profile` key selects which tier of hooks runs:

| Profile    | Hooks that run                                                              |
| ---------- | -------------------------------------------------------------------------- |
| `minimal`  | branch protection, secret protection, system protection, stop-phrase guard |
| `standard` | everything in `minimal`, plus commit-message validation and the uv nudge   |
| `strict`   | same as `standard` (reserved for future additions)                         |

`standard` is the default. To run only the safety hooks:

```toml
profile = "minimal"
```

### Turn off individual hooks

Use `disabled_hooks` to force a hook off no matter the profile:

```toml
disabled_hooks = ["use-uv", "commit-message"]
```

### Tune hook strictness

The `protect-system` and `protect-secrets` hooks take a `level` that controls
how much they block, from loosest to strictest:

- `critical` blocks only catastrophic, unrecoverable operations.
- `high` (the default) adds significant-risk operations.
- `strict` adds cautionary operations on top of `high`.

Set a level per hook:

```toml
[hooks.protect-system]
level = "strict"

[hooks.protect-secrets]
level = "critical"
```

## License

Released under the [MIT License](LICENSE). You're welcome to fork or borrow
code, but the personal-use caveat above still applies in spirit: don't expect
this repo to behave like a maintained product.
