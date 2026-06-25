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

- Branch protection blocks destructive git operations, direct commits, and
  merge commits to `main`/`master`.
- Secret protection blocks reading, editing, or exfiltrating sensitive files.
- System protection blocks system-destructive shell commands.
- Commit-message validation holds `git commit` and `gh pr` titles to
  conventional-commit format.
- Config protection blocks edits that weaken a linter, formatter, or
  typechecker config (including the `[tool.*]` tables in `pyproject.toml`),
  while still allowing dependency and metadata changes and first-time setup.
- The uv nudge suggests `uv run` when it sees a bare `python`, `pip`, `pytest`,
  or `ruff` call.
- The stop-phrase guard stops Claude from ending a turn with certain filler
  phrases.
- The follow-up capture hook stops Claude from ending a turn that names
  deferred work (out-of-scope items, follow-up PRs, TODOs) without either
  doing it or recording it in the backlog (`.agent/BACKLOG.md` by default).

### Skills Claude loads on its own

Claude pulls these in when the task matches, no action needed:

- `documentation-writer` for writing and editing user-facing docs.
- `safe-refactoring` for behavior-preserving restructuring in any language.
- `flask-development` for building Flask 3+ apps.
- `htmx-expert` for writing and debugging htmx.
- `accessibility` for auditing web UI against WCAG 2.2 while editing templates.
- `nclutils` for code that uses the `nclutils` library.
- `tufte-viz` for critiquing data visualizations against Tufte's principles.

### Slash commands you invoke

Type these yourself when you want them:

- `/pr` commits outstanding work, runs the tests, pushes the branch, and opens
  a pull request.
- `/squash` collapses a finished branch into one commit on `main`, then cleans
  up the branch.
- `/fast-forward` lands a finished branch onto the local `main`/`master` as a
  fast-forward of its logically grouped commits (no merge commit, no squash),
  then deletes the branch and removes its worktree; local only, never pushes.
- `/cleanup-branch` repackages the current branch's commits into fewer, logically
  grouped, reviewable commits without changing the resulting code; it backs up
  first, verifies the tree is byte-for-byte identical, and never pushes.
- `/gha` investigates a GitHub Actions failure and suggests a fix.
- `/refactor` runs a multi-agent, behavior-preserving refactor review of any code, with
  `--quick` for a fast pass and `--fix` to apply the safe changes.
- `/organize` reviews how a project is organized (file/directory layout, naming, module
  boundaries, grab-bag files) and returns a report plus an ordered reorganization plan; it
  is advisory and never moves files.
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
| `standard` | everything in `minimal`, plus commit-message validation, config protection, the uv nudge, and follow-up capture |
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

### Set the follow-up backlog path

The `capture-followups` hook takes a `backlog` path (relative to the project
root) that sets where it expects deferred work to be recorded; writing that file
during the turn satisfies the hook. It defaults to `.agent/BACKLOG.md`:

```toml
[hooks.capture-followups]
backlog = ".agent/BACKLOG.md"
```

### Add project-specific rules

Five hooks read an optional per-project rules file and add its rules to their
built-in ones: `protect-secrets`, `protect-system`, `stop-phrase-guard`,
`capture-followups`, and `config-protection`. Drop a file named after the hook
under your project's
`.claude/natelandau-toolkit/` directory:

    <project>/.claude/natelandau-toolkit/protect_secrets.rules.toml

These rules are additive only: a project can add blocks but never weaken or
remove a built-in one. To turn a hook off entirely use `disabled_hooks`. A
malformed project file is ignored (the hook warns and keeps enforcing its
built-in rules), and the file is read whether or not you also keep a
`natelandau-toolkit.toml`.

Each file uses the same format as the hook's built-in rules. For example, to
block a project's production config from being read or edited:

```toml
# <project>/.claude/natelandau-toolkit/protect_secrets.rules.toml
[[rule]]
id      = "acme-prod-conf"
reason  = "production secrets live in this file"
field   = "file_path"
pattern = 'acme-prod\.conf$'
```

`pattern` may be a single regex (as above) or a list of regexes, which match if
any one hits — handy for folding several paths into one rule:

```toml
[[rule]]
id      = "acme-secrets"
reason  = "Acme credential files"
field   = "file_path"
pattern = ['acme-prod\.conf$', '(?:^|/)\.acme/token$']
```

Match the array name to the hook's built-in file: `[[rule]]` for
`protect-secrets` and `protect-system`, `[[violation]]` for `stop-phrase-guard`,
`[[trigger]]` for `capture-followups`, and `protected_files` /
`protected_pyproject_tables` lists for `config-protection`. A `protect-secrets` rule must target a named `field` (or
use `conditions`), since that hook has no single primary text for a bare
`pattern` to match against.

## Contributing

Development setup, running the test gates, the hooks stage-dispatcher model, and instructions for adding hooks, skills, commands, and agents all live in [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Released under the [MIT License](LICENSE). You're welcome to fork or borrow
code, but the personal-use caveat above still applies in spirit: don't expect
this repo to behave like a maintained product.
