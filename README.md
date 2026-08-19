# natelandau-cc-plugin

A personal [Claude Code](https://code.claude.com) marketplace containing one plugin: guardrails and workflow tooling for everyday coding.

> [!WARNING]
> This is a personal toolkit, built for one developer's machine and habits. It's opinionated about tools (uv, ruff, conventional commits), workflows, and what counts as "safe." It changes whenever those habits change, often without notice and without backward compatibility. Install it to study or fork it, not as a stable dependency. Pin to a tag if you need things to stay put.

## What you get

Adding the marketplace gives you one plugin, `natelandau-toolkit`: PreToolUse and Stop hooks that block risky actions, on-demand skills, slash commands, and review subagents.

## Requirements

The plugin runs its hooks as standalone Python scripts through [uv](https://docs.astral.sh/uv/), so you need a working install before it does anything.

- Claude Code (the host for all components).
- `uv` on your `PATH`. The hook scripts launch with `uv run`, and uv fetches the required Python (3.14+) on first run.
- `git`. The branch-protection hook reads repository state.

## Install

You install in two steps: register the marketplace, then install the plugin. Run these inside Claude Code.

1. Add the marketplace from GitHub:

    ```
    /plugin marketplace add natelandau/cc-plugin
    ```

2. Install the plugin:

    ```
    /plugin install natelandau-toolkit@natelandau-cc-plugin
    ```

That's it. Hooks register automatically, and skills, commands, and subagents become available right away. To confirm, run `/plugin` and check that the plugin appears as enabled.

## natelandau-toolkit

This plugin combines four kinds of components: hooks that enforce rules, skills that add knowledge or run workflows, slash commands, and subagents.

### Hooks

Hooks run automatically on every matching tool call. They block an action and explain why, so a guardrail holds even when the model would rather not. The active set depends on your profile (see [Configuration](#configuration)).

| Hook                   | Blocks                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `branch-protection`    | Destructive git operations (any branch), plus file edits and direct commits on `main` or `master`. Merge commits onto `main`/`master` (from `merge`/`pull`) prompt for approval rather than being blocked outright. Checks are keyed off the branch of the file or repo each action targets, so they hold no matter which directory the shell sits in. Paths inside an exempt tree, declared in your global config or `$NATELANDAU_TOOLKIT_EXEMPT_PATHS`, skip the protected-branch rules but not the destructive ones. See [docs/branch-protection.md](docs/branch-protection.md) for the full allow/block/ask rules.                                                                                                                                                                                       |
| `protect-secrets`      | Reading, editing, writing, or exfiltrating sensitive files like `.env` and credential stores.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| `protect-system`       | System-destructive shell commands, plus removal of a `.git` directory (paths inside it stay allowed).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| `protect-remote`       | Remote-host commands (ssh, scp, sftp, remote rsync, ansible). Prompts for approval rather than blocking; you judge destructiveness per invocation.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| `confirm-recursive-rm` | Recursive deletes (`rm -rf` and every other flag spelling) whose targets are not all rebuildable. Prompts for approval rather than blocking. Deletes confined to a temp root (`/tmp/`, `/private/tmp/`, or the literal `$TMPDIR/`) or to a directory a toolchain regenerates (`node_modules`, `.venv`, `.tox`, `.nox`, `__pycache__`, `.pytest_cache`, `.ruff_cache`, `.mypy_cache`, `.ipynb_checkpoints`, `htmlcov`) run without interruption; one non-exempt target prompts for the whole command. Paths are matched as written, so a macOS `$TMPDIR` already expanded to `/var/folders/...` is hard-blocked by `protect-system` instead. |
| `commit-message`       | Commits and PR titles that don't follow conventional-commit format. Commands aimed at an exempt tree (see `branch-protection`) are exempt.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| `config-protection`    | Edits that weaken a linter, formatter, or typechecker config.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| `use-uv`               | Nothing. It's a non-blocking nudge toward `uv run` for Python commands.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |

### Knowledge skills

These skills load on demand when your task matches. You don't invoke them by name. They give the model current, focused guidance on a tool or domain.

| Skill               | Use when you're working with                                                                                                                                |
| ------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `accessibility`     | Web UI accessibility: ARIA, keyboard nav, focus, contrast, WCAG 2.2.                                                                                        |
| `daisyui`           | daisyUI v5 and Tailwind CSS components, forms, and theming.                                                                                                 |
| `explain-diff`      | Understanding a code change, diff, branch, or PR as concepts and features rather than lines; produces an HTML explainer.                                    |
| `flask-development` | Flask 3+ apps using the app-factory pattern and blueprints.                                                                                                 |
| `gha`               | Investigating GitHub Actions failures and finding the root cause.                                                                                           |
| `htmx-expert`       | htmx attributes, AJAX fragments, swaps, and hypermedia patterns.                                                                                            |
| `nclutils`          | Python projects that depend on the `nclutils` package.                                                                                                      |
| `safe-refactoring`  | Behavior-preserving refactors in any language.                                                                                                              |
| `technical-writer`  | READMEs, changelogs, guides, and other user-facing prose. Governs document structure and applies ASD-STE100 Simplified Technical English to every sentence. |
| `tortoise-orm`      | Tortoise ORM v1.x models, queries, relations, and migrations.                                                                                               |
| `tufte-viz`         | Designing or critiquing data visualizations with Tufte's principles.                                                                                        |
| `zensical`          | Authoring docs with the Zensical static-site engine: config, admonitions, Mermaid, tabs, grids.                                                             |

### Workflow commands

These run multi-step workflows. Some are slash commands, others are skills you trigger with a slash. You invoke them deliberately; they never fire on their own. The git workflows are local-only and never push unless they say so.

| Command                                | What it does                                                                                                                                                          |
| -------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `/refactor [--quick] [--fix] [target]` | Multi-agent review for refactor opportunities, refutes weak findings, and optionally applies the safe ones.                                                           |
| `/organize [target]`                   | Reviews project structure and produces a prioritized reorganization plan. Advisory only; never moves files.                                                           |
| `/prune-comments`                      | Reviews the current changes and cleans up their inline comments, keeping non-obvious why-comments and dropping redundant ones. Edits the working tree; never commits. |
| `/create-prd`                          | Generates a Product Requirements Document from the conversation.                                                                                                      |
| `/pr`                                  | Commits outstanding work, runs linters and tests, pushes the branch, and opens a PR with a conventional-commit title.                                                 |
| `/cleanup-branch`                      | Regroups the current branch's commits into fewer reviewable commits without changing the resulting code.                                                              |
| `/squash`                              | Squash-merges a finished branch into one commit on `main`, then deletes the branch. Irreversible.                                                                     |
| `/fast-forward`                        | Lands a finished branch onto local `main` as a fast-forward of regrouped commits, then cleans up. Irreversible.                                                       |

### Subagents

The review commands above delegate to focused subagents that run in their own context and return a short summary. You can also call them directly when you want their narrow job done without filling the main conversation.

| Subagent             | Job                                                                                                                                |
| -------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| `test-runner`        | Runs the project's linters and test suite, returns a pass/fail summary.                                                            |
| `doc-drift-reviewer` | Compares user-facing docs against the current branch and lists stale or missing coverage.                                          |
| `review-finder`      | Applies one analysis angle to a scope and returns candidate findings.                                                              |
| `review-verifier`    | Judges a candidate finding as kept, plausible, or refuted with a cited reason.                                                     |
| `comment-pruner`     | Rewrites the inline comments in a change, keeping non-obvious why-comments and dropping the rest. Edits comments only, never code. |

## Configuration

The plugin reads an optional TOML config file. Settings cascade: a global file at `~/.claude/natelandau-toolkit.toml` applies everywhere, and a project file at `<project>/.claude/natelandau-toolkit.toml` overrides it key by key. Every key is optional, so you can skip configuration entirely and take the defaults.

The plugin ships a `natelandau-toolkit.toml.example` template under its `hooks/` directory. Copy it to one of the paths above and edit.

### Profiles and disabling hooks

The toolkit groups its hooks into three profiles. `profile` selects the tier; `disabled_hooks` force-off individual hooks by id regardless of profile.

| Profile              | Active hooks                                                                                  |
| -------------------- | --------------------------------------------------------------------------------------------- |
| `minimal`            | branch-protection, protect-secrets, protect-system.                                           |
| `standard` (default) | minimal plus protect-remote, confirm-recursive-rm, commit-message, config-protection, use-uv. |
| `strict`             | Same as standard, reserved for future use.                                                    |

```toml
# ~/.claude/natelandau-toolkit.toml
profile = "standard"
disabled_hooks = ["config-protection"]
```

You can also add project-specific rules without touching the built-in ones. The protect-secrets, protect-system, protect-remote, and config-protection hooks read an extra rules file from `<project>/.claude/natelandau-toolkit/<hook>.rules.toml`. These rules are additive: they can add new blocks but never weaken a built-in rule. A protect-remote rule may set `action = "ask"` or `"block"` (default `block`); a project `block` takes priority over the built-in prompts, so you can hard-stop specific remote commands per project. To turn a hook off, use `disabled_hooks`. The config template documents the schema.

## Uninstalling

Remove the plugin, then the marketplace, from inside Claude Code:

```
/plugin uninstall natelandau-toolkit@natelandau-cc-plugin
/plugin marketplace remove natelandau-cc-plugin
```

## Contributing

This is a personal project, but the internals are documented for anyone forking it. See [CONTRIBUTING.md](CONTRIBUTING.md) for the architecture, the hook plugin contract, testing, and how to add a component.

## License

Released under the [MIT License](LICENSE).
