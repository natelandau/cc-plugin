# natelandau-cc-plugin

A personal [Claude Code](https://code.claude.com) marketplace: guardrails and workflow tooling for everyday coding, split into plugins so that each repository loads only the skills it uses.

> [!WARNING]
> This is a personal toolkit, built for one developer's machine and habits. It's opinionated about tools (uv, ruff, conventional commits), workflows, and what counts as "safe." It changes whenever those habits change, often without notice and without backward compatibility. Install it to study or fork it, not as a stable dependency. Pin to a tag if you need things to stay put.

## What you get

The marketplace ships eight plugins. Two of them are for every project. The others each cover one stack, and you install them only in the repositories that use that stack, so their skill descriptions do not take context in other projects.

| Plugin                     | Install scope | Contents                                                                               |
| -------------------------- | ------------- | -------------------------------------------------------------------------------------- |
| `natelandau-toolkit`       | User          | Safety hooks, review commands, a documentation-writing skill, and branch explainers.   |
| `natelandau-git`           | User          | Branch workflows: pull requests, squash and fast-forward landings, post-merge cleanup. |
| `natelandau-web-ui`        | Local         | The `htmx-expert` and `daisyui` skills.                                                |
| `natelandau-flask`         | Local         | The `flask-development` skill.                                                         |
| `natelandau-tortoise`      | Local         | The `tortoise-orm` skill.                                                              |
| `natelandau-nclutils`      | Local         | The `nclutils` skill, for Python projects that depend on the `nclutils` package.       |
| `natelandau-zensical`      | Local         | The `zensical` skill, for documentation sites built with Zensical.                     |
| `natelandau-visualization` | Local         | The `tufte-viz` skill, for chart design and critique.                                  |

The `natelandau-git` and `natelandau-zensical` plugins depend on `natelandau-toolkit`. Claude Code installs it with them if it is not already installed.

## Requirements

The core plugin runs its hooks as standalone Python scripts through [uv](https://docs.astral.sh/uv/), so you need a working install before it does anything.

- Claude Code (the host for all components).
- `uv` on your `PATH`. The hook scripts launch with `uv run`, and uv fetches the required Python (3.14+) on first run.
- `git`. The branch-protection hook reads repository state.

## Install

The install scope decides where a plugin is active. User scope turns a plugin on in every project. Local scope turns it on for you in one repository only, and records it in that repository's `.claude/settings.local.json`.

The commands below run in a shell. To run one from inside Claude Code, type `!` before it, for example `! claude plugin install natelandau-git@natelandau-cc-plugin`. After you install a plugin from an open session, run `/reload-plugins`.

1. Add the marketplace from GitHub:

    ```shell
    claude plugin marketplace add natelandau/cc-plugin
    ```

2. Install the two plugins for every project at user scope:

    ```shell
    claude plugin install natelandau-toolkit@natelandau-cc-plugin
    claude plugin install natelandau-git@natelandau-cc-plugin
    ```

3. In each repository that uses a stack, go to the repository directory and run the line for that stack. Each line installs one plugin at local scope.

    ```shell
    claude plugin install natelandau-web-ui@natelandau-cc-plugin --scope local         # htmx and daisyUI
    claude plugin install natelandau-flask@natelandau-cc-plugin --scope local          # Flask
    claude plugin install natelandau-tortoise@natelandau-cc-plugin --scope local       # Tortoise ORM
    claude plugin install natelandau-nclutils@natelandau-cc-plugin --scope local       # nclutils package
    claude plugin install natelandau-zensical@natelandau-cc-plugin --scope local       # Zensical docs
    claude plugin install natelandau-visualization@natelandau-cc-plugin --scope local  # data visualization
    ```

To confirm the result, run `/plugin` and look at the **Installed** tab, which lists each plugin with its scope.

> **Note:** Project scope (`--scope project`) records the plugin in the committed `.claude/settings.json` and turns it on for every collaborator. A collaborator who has not added this marketplace then gets a "not installed" error from Claude Code.

### Update

Updating a plugin does not install plugins that are new to the marketplace. After you update, install any plugin from the steps above that `/plugin` does not list as installed.

```shell
claude plugin marketplace update natelandau-cc-plugin
claude plugin update natelandau-toolkit@natelandau-cc-plugin
claude plugin update natelandau-git@natelandau-cc-plugin
```

## natelandau-toolkit

The core plugin holds the hooks, the subagents that other components dispatch, two skills that load when your task matches, and four workflows that run only when you type their command.

### Hooks

Hooks run automatically on every matching tool call. They block an action and explain why, so a guardrail holds even when the model would rather not. The active set depends on your profile (see [Configuration](#configuration)).

| Hook                   | Blocks                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `branch-protection`    | Destructive git operations (any branch), plus file edits and direct commits on `main`, `master`, or any branch listed in `[hooks.branch-protection] protected_branches`. Merge commits onto a protected branch (from `merge`/`pull`) prompt for approval rather than being blocked outright. Checks are keyed off the branch of the file or repo each action targets, so they hold no matter which directory the shell sits in. Paths inside an exempt tree, declared in your global config or `$NATELANDAU_TOOLKIT_EXEMPT_PATHS`, skip the protected-branch rules but not the destructive ones. See [docs/branch-protection.md](docs/branch-protection.md) for the full allow/block/ask rules.                                                                                                                                                                                       |
| `protect-secrets`      | Reading, editing, writing, or exfiltrating sensitive files like `.env` and credential stores.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| `protect-system`       | System-destructive shell commands, plus removal of a `.git` directory (paths inside it stay allowed). The rules also match against the command with its own variable assignments resolved, so `S=~; rm -rf "$S"` is blocked.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| `protect-remote`       | Remote-host commands (ssh, scp, sftp, remote rsync, ansible). Prompts for approval rather than blocking; you judge destructiveness per invocation. Hosts you list in `trusted_remote_hosts` in the global config run without a prompt.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| `confirm-recursive-rm` | Recursive deletes (`rm -rf` and every other flag spelling) whose targets are not all rebuildable. Prompts for approval rather than blocking. Deletes confined to a temp root (`/tmp/`, `/private/tmp/`, or the literal `$TMPDIR/`) or to a directory a toolchain regenerates (`node_modules`, `.venv`, `.tox`, `.nox`, `__pycache__`, `.pytest_cache`, `.ruff_cache`, `.mypy_cache`, `.ipynb_checkpoints`, `htmlcov`) run without interruption; one non-exempt target prompts for the whole command. A path the command assigns to one of its own variables is resolved before the match, so `S=/tmp/work; rm -rf "$S/out"` counts as a temp path. Other paths match as written, so a macOS `$TMPDIR` already expanded to `/var/folders/...` is hard-blocked by `protect-system` instead. |
| `commit-message` | Commit messages and PR titles and bodies that break the rules in `[hooks.commit-message]` (see [Commit message rules](#commit-message-rules)). Commands aimed at an exempt tree (see `branch-protection`) are exempt. |
| `config-protection`    | Edits that weaken a linter, formatter, or typechecker config.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| `use-uv`               | Nothing. It's a non-blocking nudge toward `uv run` for a bare `python`, `pytest`, or `ruff` that the project's own `.venv` provides, and toward `uv add` for `pip install` inside a project with a `.venv`. A tool the venv lacks is assumed to live on your PATH and is left alone, as is any explicitly path-qualified executable such as `~/.local/bin/ruff`.                                                                                                                                                                                                                                                                                 |

### Skills

These skills load when your task matches. You do not call them by name.

| Skill              | Use when you're working with                                                                                                                                |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `safe-refactoring` | Behavior-preserving refactors in any language.                                                                                                              |
| `technical-writer` | READMEs, changelogs, guides, and other user-facing prose. Governs document structure and applies ASD-STE100 Simplified Technical English to every sentence. |

### Commands

These workflows run only when you type the command. Claude does not start them on its own, so their descriptions take no context until you use them.

| Command                                | What it does                                                                                                         |
| -------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| `/refactor [--quick] [--fix] [target]` | Multi-agent review for refactor opportunities, refutes weak findings, and optionally applies the safe ones.          |
| `/organize [target]`                   | Reviews project structure and produces a prioritized reorganization plan. Advisory only; never moves files.          |
| `/explain-diff`                        | Explains a code change, diff, branch, or PR as concepts and features rather than lines, in an HTML explainer.        |
| `/walkthrough`                         | Captures stills and clips of the web, iOS, macOS, or Android UI an agent built, in a local HTML walkthrough.         |

### Subagents

Other components dispatch these subagents. Each one runs in its own context and returns a short summary. They are not meant for direct use.

| Subagent          | Job                                                                                         | Dispatched by                          |
| ----------------- | ------------------------------------------------------------------------------------------- | -------------------------------------- |
| `test-runner`     | Runs the project's linters and test suite, returns a pass/fail summary.                     | `/refactor` and the `natelandau-git` workflows |
| `review-finder`   | Applies one analysis angle to a scope and returns candidate findings.                       | `/refactor` and `/organize`            |
| `review-verifier` | Judges a candidate finding as kept, plausible, or refuted with a cited reason.              | `/refactor` and `/organize`            |

## natelandau-git

The `natelandau-git` plugin runs branch workflows. The git workflows are local-only and never push unless they say so. Claude runs `/pull-request`, `/squash`, `/fast-forward`, and `/cleanup-branch` on its own when you ask in plain words to open a PR, squash a branch into `main`, merge a branch into `main`, or clean up after a merged PR. The other two run only when you type the command.

| Command            | What it does                                                                                                                                                |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `/pull-request`    | Commits outstanding work, runs linters and tests, pushes the branch, and opens a PR whose title and lead paragraph become the squash commit.                 |
| `/regroup-commits` | Regroups the current branch's commits into fewer reviewable commits without changing the resulting code.                                                    |
| `/squash`          | Squash-merges a finished branch into one commit on `main`, then deletes the branch. Irreversible.                                                           |
| `/fast-forward`    | Lands a finished branch onto local `main` as a fast-forward of regrouped commits, then cleans up. Irreversible.                                             |
| `/cleanup-branch`  | After a PR merges on the remote, removes the local worktree and branch and fast-forwards `main`. Asks before deleting a branch with work the merge left out. |
| `/gha`             | Investigates GitHub Actions failures and finds the root cause.                                                                                              |

The finishing steps of `/pull-request`, `/squash`, and `/fast-forward` dispatch the `doc-drift-reviewer` subagent, which compares user-facing docs against the branch and lists stale or missing coverage. They also dispatch `test-runner` from the core plugin.

## Stack plugins

Each stack plugin holds skills that load when your task matches, in the repositories where you installed the plugin.

| Plugin                     | Skill               | Use when you're working with                                                                    |
| -------------------------- | ------------------- | ----------------------------------------------------------------------------------------------- |
| `natelandau-web-ui`        | `htmx-expert`       | htmx attributes, AJAX fragments, swaps, and hypermedia patterns.                                |
| `natelandau-web-ui`        | `daisyui`           | daisyUI v5 and Tailwind CSS components, forms, and theming.                                     |
| `natelandau-flask`         | `flask-development` | Flask 3+ apps using the app-factory pattern and blueprints.                                     |
| `natelandau-tortoise`      | `tortoise-orm`      | Tortoise ORM v1.x models, queries, relations, and migrations.                                   |
| `natelandau-nclutils`      | `nclutils`          | Python projects that depend on the `nclutils` package.                                          |
| `natelandau-zensical`      | `zensical`          | Authoring docs with the Zensical static-site engine: config, admonitions, Mermaid, tabs, grids. |
| `natelandau-visualization` | `tufte-viz`         | Designing or critiquing data visualizations with Tufte's principles.                            |

## Configuration

The core plugin reads an optional TOML config file for its hooks. Settings cascade: a global file at `~/.claude/natelandau-toolkit.toml` applies everywhere, and a project file at `<project>/.claude/natelandau-toolkit.toml` overrides it key by key. Every key is optional, so you can skip configuration entirely and take the defaults.

The core plugin ships a `natelandau-toolkit.toml.example` template under its `hooks/` directory. Copy it to one of the paths above and edit.

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

### Commit message rules

The `commit-message` hook checks `git commit -m` messages and `gh pr create|edit|merge` titles and bodies. Its defaults follow commitlint's `config-conventional`. Set the options in a `[hooks.commit-message]` table. A project file can loosen the global rules, because these rules control style and not safety.

| Option                        | Default                                                                         | Effect                                                                                       |
| ----------------------------- | ------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| `format`                      | `"conventional"`                                                                | `"conventional"` requires `<type>(<scope>): <subject>`. `"none"` skips the type and format checks. |
| `types`                       | `build`, `chore`, `ci`, `docs`, `feat`, `fix`, `perf`, `refactor`, `revert`, `style`, `test` | The allowed commit types.                                                                    |
| `require_scope`               | `false`                                                                         | Requires a `(scope)` after the type.                                                         |
| `max_subject_length`          | `100`                                                                           | The maximum length of the first line, with the type and scope. `0` removes the limit.        |
| `max_body_line_length`        | `0`                                                                             | The maximum length of a body line. `0` removes the limit. URL lines and git trailers are exempt. |
| `subject_case`                | `"lower-first"`                                                                 | `"lower-first"` blocks an uppercase first letter. `"any"` allows it.                         |
| `forbid_trailing_punctuation` | `true`                                                                          | Blocks a subject that ends with `.`, `!`, or `?`.                                            |
| `forbid_wip_subject`          | `true`                                                                          | Blocks a subject that starts with a WIP or Draft marker.                                     |
| `force_imperative`            | `false`                                                                         | Blocks a subject whose first word is a past-tense, "-ing", or "-s" form of a verb in `hooks/pretooluse/enforce_commit_message.verbs.txt`, or a word that file denies. |
| `forbidden_patterns`          | `[]`                                                                            | Regular expressions. A match anywhere in the message, PR title, or PR body blocks the command. |
| `check_pr_titles`             | `true`                                                                          | Applies the subject rules to PR titles. `forbidden_patterns` applies in all cases.           |

```toml
# ~/.claude/natelandau-toolkit.toml
[hooks.commit-message]
max_subject_length = 70
force_imperative = true
forbidden_patterns = ['(?im)^Co-Authored-By:.*Claude']
```

The verb file lists base verbs, one per line. A `form -> verb` line maps an irregular form, a `!word` line marks a word that is never blocked, and a `-word` line rejects a word as the first word. The file ships inside the plugin directory, which an update replaces, so a local edit does not survive an update. Change the list in a fork, or reapply the edit after each update.

The `/pull-request`, `/squash`, and `/fast-forward` skills do not impose a message format. They write messages to your own commit conventions, and this hook enforces the rules you configure.

### Project rules files

You can also add project-specific rules without touching the built-in ones. The protect-secrets, protect-system, protect-remote, and config-protection hooks read an extra rules file from `<project>/.claude/natelandau-toolkit/<hook>.rules.toml`. These rules are additive: they can add new blocks but never weaken a built-in rule. A protect-remote rule may set `action = "ask"` or `"block"` (default `block`); a project `block` takes priority over the built-in prompts, so you can hard-stop specific remote commands per project. To turn a hook off, use `disabled_hooks`. The config template documents the schema.

## Uninstalling

Remove each installed plugin, then the marketplace, from inside Claude Code. Uninstall a local-scope plugin from inside the repository where you installed it.

```
/plugin uninstall natelandau-git@natelandau-cc-plugin
/plugin uninstall natelandau-toolkit@natelandau-cc-plugin
/plugin marketplace remove natelandau-cc-plugin
```

## Contributing

This is a personal project, but the internals are documented for anyone forking it. See [CONTRIBUTING.md](CONTRIBUTING.md) for the architecture, the hook plugin contract, testing, and how to add a component.

## License

Released under the [MIT License](LICENSE).
