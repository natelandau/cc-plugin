# natelandau-cc-plugin

A personal [Claude Code](https://code.claude.com) plugin marketplace. It adds safety hooks that block dangerous tool calls, and skills that teach Claude repeatable workflows for git, code review, documentation, and specific frameworks.

> [!WARNING]
> This is a personal toolkit, built for one developer's machine and habits. It is opinionated about tools (uv, ruff, conventional commits), workflows, and what counts as "safe." It changes when those habits change, often without notice and without backward compatibility. Install it to study or fork it, not as a stable dependency. Pin to a tag if you need a fixed version.

## What is in the marketplace

A marketplace is a catalog that Claude Code installs plugins from. This marketplace holds seven plugins. Each plugin is a bundle of components:

- Hooks are scripts that Claude Code runs before a tool call. They can block the call or ask you to approve it.
- Skills are instruction files that Claude reads when it does a matching task, or when you type the skill's slash command.
- Subagents are helpers that a skill starts to do one part of its job in a separate context.

Two plugins are for every project. The other five each cover one stack. Every skill that Claude can start on its own adds its description to the context of each session. For this reason, we recommend that you install a stack plugin only in the repositories that use that stack. You can install any plugin at any scope.

| Plugin                | Recommended scope | Contents                                                                                      |
| --------------------- | ----------------- | --------------------------------------------------------------------------------------------- |
| `natelandau-toolkit`  | User          | All hooks, plus skills for refactoring, project review, documentation, and change explainers. |
| `natelandau-git`      | User          | Skills for pull requests, squash and fast-forward merges, commit regrouping, and CI failures. |
| `natelandau-htmx`     | Local         | A skill for htmx.                                                                             |
| `natelandau-flask`    | Local         | A skill for Flask 3 applications.                                                             |
| `natelandau-tortoise` | Local         | A skill for Tortoise ORM v1.                                                                  |
| `natelandau-nclutils` | Local         | A skill for Python projects that depend on the `nclutils` package.                            |
| `natelandau-zensical` | Local         | A skill for documentation sites built with Zensical.                                          |

The `natelandau-git` and `natelandau-zensical` plugins depend on `natelandau-toolkit`. If `natelandau-toolkit` is not installed, Claude Code installs it with them.

## Requirements

The hooks run as Python scripts through [uv](https://docs.astral.sh/uv/). Without uv, the hooks do not run.

- Claude Code.
- `uv` on your `PATH`. On the first run, uv downloads the Python version that the hooks need (3.14 or later).
- `git`. The branch-protection hook reads the repository state.

## Install

The install scope controls where a plugin is active. User scope enables a plugin in every project. Local scope enables it for you in one repository only, and records it in that repository's `.claude/settings.local.json`. The steps below use the recommended scope for each plugin. To use a different scope, change or remove the `--scope` flag.

The commands below run in a shell. To run one from inside Claude Code, type `!` before it, for example `! claude plugin install natelandau-git@natelandau-cc-plugin`. If you install a plugin from an open session, run `/reload-plugins` after.

1. Add the marketplace from GitHub:

    ```shell
    claude plugin marketplace add natelandau/cc-plugin
    ```

2. Install the two plugins for every project at user scope:

    ```shell
    claude plugin install natelandau-toolkit@natelandau-cc-plugin
    claude plugin install natelandau-git@natelandau-cc-plugin
    ```

3. Install the stack plugins that you use. For local scope, go to the directory of each repository that uses the stack, and run the line for that stack there. To enable a stack plugin in every project, remove `--scope local`.

    ```shell
    claude plugin install natelandau-htmx@natelandau-cc-plugin --scope local      # htmx
    claude plugin install natelandau-flask@natelandau-cc-plugin --scope local     # Flask
    claude plugin install natelandau-tortoise@natelandau-cc-plugin --scope local  # Tortoise ORM
    claude plugin install natelandau-nclutils@natelandau-cc-plugin --scope local  # nclutils package
    claude plugin install natelandau-zensical@natelandau-cc-plugin --scope local  # Zensical docs
    ```

4. Run `/plugin` in Claude Code and open the **Installed** tab. Make sure that each plugin shows the scope that you chose.

> **Note:** Project scope (`--scope project`) records the plugin in the committed `.claude/settings.json` and enables it for every collaborator. A collaborator who has not added this marketplace then gets a "not installed" error from Claude Code.

### Update

An update does not install plugins that are new to the marketplace. After you update, install each plugin from the steps above that `/plugin` does not show as installed.

```shell
claude plugin marketplace update natelandau-cc-plugin
claude plugin update natelandau-toolkit@natelandau-cc-plugin
claude plugin update natelandau-git@natelandau-cc-plugin
```

### Uninstall

Remove each plugin, then remove the marketplace. Remove a local-scope plugin from inside the repository where you installed it.

```shell
claude plugin uninstall natelandau-git@natelandau-cc-plugin
claude plugin uninstall natelandau-toolkit@natelandau-cc-plugin
claude plugin marketplace remove natelandau-cc-plugin
```

## Hooks

A hook is a script that Claude Code runs automatically at a point in a session. The hooks in this marketplace run before each `Read`, `Edit`, `Write`, `NotebookEdit`, and `Bash` tool call. Each hook examines the call and does one of three things:

- Allows the call.
- Blocks the call, and tells Claude the reason.
- Asks you to approve the call, with the standard Claude Code permission prompt.

Claude Code runs hooks outside the model, so a hook holds even when Claude tries to work around it. All hooks are in the `natelandau-toolkit` plugin. If a hook fails internally, it allows the call, so a hook error never stops your work.

| Hook                   | What it does                                                                                                                                                                                                                                                                                                                                          |
| ---------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `branch-protection`    | Blocks destructive git commands on any branch. On a protected branch (`main`, `master`, and the branches you add), blocks file edits and direct commits, and asks before a merge commit. The hook checks the branch of the file or repository that each call targets. See [docs/branch-protection.md](docs/branch-protection.md) for the full rules. |
| `protect-secrets`      | Blocks reads, edits, writes, and exfiltration of sensitive files, such as `.env` files and credential stores.                                                                                                                                                                                                                                         |
| `protect-system`       | Blocks shell commands that destroy system files, and removal of a `.git` directory. The hook resolves variables that the command assigns, so `S=~; rm -rf "$S"` is blocked.                                                                                                                                                                         |
| `protect-remote`       | Asks before remote-host commands: `ssh`, `scp`, `sftp`, remote `rsync`, and `ansible`. Commands to a host in `trusted_remote_hosts` run without a prompt.                                                                                                                                                                                           |
| `confirm-recursive-rm` | Asks before a recursive delete (`rm -rf` in any flag spelling), unless every target is in a temp directory or is a directory that a tool rebuilds, such as `node_modules`, `.venv`, or `__pycache__`.                                                                                                                                               |
| `commit-message`       | Blocks a `git commit -m` message, or a `gh pr` title or body, that breaks the rules in `[hooks.commit-message]`.                                                                                                                                                                                                                                     |
| `config-protection`    | Blocks edits that make a linter, formatter, or typechecker config less strict.                                                                                                                                                                                                                                                                        |
| `use-uv`               | Blocks nothing. It tells Claude to use `uv run` for a bare `python`, `pytest`, or `ruff` that the project's `.venv` provides, and `uv add` in place of `pip install`.                                                                                                                                                                              |

### Enable and disable hooks

The hooks are enabled when you install `natelandau-toolkit`. Two keys in the [config file](#configure-hooks) control which hooks run. The `profile` key selects a set of hooks, and the `disabled_hooks` key disables individual hooks in any profile.

| Profile              | Hooks that run                                                                                                       |
| -------------------- | -------------------------------------------------------------------------------------------------------------------- |
| `minimal`            | `branch-protection`, `protect-secrets`, `protect-system`.                                                            |
| `standard` (default) | The `minimal` hooks, plus `protect-remote`, `confirm-recursive-rm`, `commit-message`, `config-protection`, `use-uv`. |
| `strict`             | The same hooks as `standard`.                                                                                        |

To disable all hooks, disable the `natelandau-toolkit` plugin with `/plugin disable`. This also disables the skills in that plugin.

### Configure hooks

The hooks read an optional TOML config file named `natelandau-toolkit.toml`. If there is no config file, the hooks use their defaults. The location of the file sets its scope:

- Global scope: put the file at `~/.claude/natelandau-toolkit.toml`. Its settings apply to every project.
- Project scope: put the file at `<project>/.claude/natelandau-toolkit.toml`. Its settings apply to that project only, and override the global settings key by key. Keys that the project file does not set keep their global values.

A project config file is committed inside the repository that the hooks protect. For this reason, a project file can make safety rules stricter but never less strict. The comments in the file below mark the keys that the hooks read from the global file only.

The file below sets every key to its default value. Copy the keys that you want to change.

```toml
# ~/.claude/natelandau-toolkit.toml

# The set of hooks that runs: "minimal", "standard", or "strict".
profile = "standard"

# Hooks to disable in any profile. IDs: branch-protection, protect-secrets,
# protect-system, protect-remote, confirm-recursive-rm, commit-message,
# config-protection, use-uv.
disabled_hooks = []

# Directory trees where the protected-branch rules and the commit message rules
# do not apply. Destructive git commands stay blocked. GLOBAL FILE ONLY.
# The NATELANDAU_TOOLKIT_EXEMPT_PATHS environment variable adds more paths,
# separated by ":".
exempt_paths = []                     # for example ["~/repos/notes-vault"]

# Hosts that protect-remote allows without a prompt: hostnames, ssh aliases,
# IP addresses, or globs. GLOBAL FILE ONLY.
trusted_remote_hosts = []             # for example ["nas", "*.lan"]

[hooks.branch-protection]
# Branches to protect in addition to main and master, by name or glob.
# The global and project lists combine, so a project cannot remove a branch.
protected_branches = []               # for example ["develop", "release/*"]

# Rules for `git commit -m` messages and `gh pr create|edit|merge` titles and
# bodies. The defaults follow commitlint's config-conventional preset.
# A project file can make these rules less strict.
[hooks.commit-message]
format = "conventional"               # "none" skips the type and format checks
types = ["build", "chore", "ci", "docs", "feat", "fix", "perf", "refactor", "revert", "style", "test"]
require_scope = false                 # require a (scope) after the type
max_subject_length = 100              # first line, with type and scope; 0 = no limit
max_body_line_length = 0              # 0 = no limit; URL lines and git trailers are exempt
subject_case = "lower-first"          # "any" allows an uppercase first letter
forbid_trailing_punctuation = true    # block a subject that ends with ".", "!", or "?"
forbid_wip_subject = true             # block a subject that starts with WIP or Draft
force_imperative = false              # block "added", "fixing", "bumps" as the first word
forbidden_patterns = []               # regexes; a match anywhere blocks the command
check_pr_titles = true                # apply the subject rules to PR titles
```

The `force_imperative` option reads its verb list from `hooks/pretooluse/enforce_commit_message.verbs.txt` in the plugin directory. An update replaces that directory, so a local edit to the file does not survive an update.

#### Project rules files

A project can add its own block rules to four hooks: `protect-secrets`, `protect-system`, `protect-remote`, and `config-protection`. Put the rules in `<project>/.claude/natelandau-toolkit/<hook>.rules.toml`, where `<hook>` is the name of the hook's built-in rules file. Project rules add blocks and never remove a built-in rule.

```toml
# <project>/.claude/natelandau-toolkit/protect_secrets.rules.toml
[[rule]]
id      = "acme-prod-conf"
reason  = "production secrets live in this file"
field   = "file_path"
pattern = 'acme-prod\.conf$'
```

A `protect-remote` rule can also set `action = "ask"` or `action = "block"`. The default is `block`. The example config file, `hooks/natelandau-toolkit.toml.example` in the plugin directory, documents the full rule schema.

## Skills

A skill is a set of instructions that Claude reads before it does a task. Each skill in this marketplace starts in one of two ways:

- Auto: Claude starts the skill when your request matches the skill's description. You can also start it with its slash command.
- Manual: the skill starts only when you type its slash command. Its description does not use context until you run it.

The slash command includes the plugin name, for example `/natelandau-toolkit:refactor` or `/natelandau-git:pull-request`. The tables below show the short name.

### natelandau-toolkit

| Skill              | Starts | What it does                                                                                                                                                    |
| ------------------ | ------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `safe-refactoring` | Auto   | Keeps a refactor behavior-preserving, in any language.                                                                                                          |
| `technical-writer` | Auto   | Writes and reviews user-facing docs, such as READMEs, changelogs, and guides. Applies ASD-STE100 Simplified Technical English.                                  |
| `/refactor`        | Manual | Reviews code for refactor opportunities with several subagents, rejects weak findings, and applies the safe ones with `--fix`. Use `--quick` for a single pass. |
| `/organize`        | Manual | Reviews the project's file and module structure and writes a prioritized reorganization plan. It does not move files.                                           |
| `/explain-diff`    | Manual | Explains a diff, branch, or PR as concepts and features, in an HTML page.                                                                                       |
| `/walkthrough`     | Manual | Captures screenshots and clips of a web, iOS, macOS, or Android UI, in a local HTML page.                                                                       |
| `/tufte-viz`       | Manual | Designs or critiques a data visualization with Edward Tufte's principles.                                                                                       |

### natelandau-git

The git skills work on your local repository. Only `/pull-request` pushes a branch, and `/cleanup-branch` deletes the remote branch only if you agree. The finishing steps of `/pull-request`, `/squash`, and `/fast-forward` run your linters and tests, and examine the docs for statements that the branch made incorrect.

| Skill              | Starts | What it does                                                                                                                             |
| ------------------ | ------ | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `/pull-request`    | Auto   | Commits open work, runs linters and tests, pushes the branch, and opens a PR. The PR title and first paragraph become the squash commit. |
| `/squash`          | Auto   | Merges a finished branch into `main` as one commit, then deletes the branch. You cannot undo this.                                       |
| `/fast-forward`    | Auto   | Regroups a finished branch into a few commits, fast-forwards local `main` to them, then deletes the branch. You cannot undo this.        |
| `/cleanup-branch`  | Auto   | After a PR merges on the remote, removes the local worktree and branch and updates `main`. Asks before it deletes unmerged work.         |
| `/regroup-commits` | Manual | Regroups the branch's commits into fewer reviewable commits. The resulting code does not change.                                         |
| `/gha`             | Manual | Finds the root cause of a GitHub Actions failure.                                                                                        |

These skills write commit messages to your own commit conventions. To enforce a format, configure the [commit message rules](#commit-message-rules).

### Stack plugins

Each stack skill starts automatically wherever its plugin is enabled.

| Plugin                | Skill               | Covers                                                                                       |
| --------------------- | ------------------- | -------------------------------------------------------------------------------------------- |
| `natelandau-htmx`     | `htmx-expert`       | htmx attributes, HTML fragment responses, swaps, and hypermedia patterns.                    |
| `natelandau-flask`    | `flask-development` | Flask 3 applications with the application factory pattern and blueprints.                    |
| `natelandau-tortoise` | `tortoise-orm`      | Tortoise ORM v1 models, queries, relations, and migrations.                                  |
| `natelandau-nclutils` | `nclutils`          | Python code in projects that depend on the `nclutils` package.                               |
| `natelandau-zensical` | `zensical`          | Documentation sites built with Zensical: config, admonitions, Mermaid diagrams, tabs, grids. |

### Enable and disable skills

The skills in a plugin are enabled when you install the plugin. Claude Code's `skillOverrides` setting does not apply to plugin skills, so use one of these methods:

- To disable every skill in a plugin, run `/plugin disable` and select the plugin. If you disable `natelandau-toolkit`, its hooks stop too.
- To stop Claude from running one skill, add a deny rule for it to `permissions.deny` in your Claude Code settings:

    ```json
    {
      "permissions": {
        "deny": ["Skill(natelandau-toolkit:safe-refactoring)"]
      }
    }
    ```

- To keep a stack skill out of a repository, do not install its plugin there.

### Subagents

The skills start these subagents for part of their work. Each subagent runs in its own context and returns a short summary. You do not use them directly.

| Subagent             | Plugin               | Job                                                                       |
| -------------------- | -------------------- | ------------------------------------------------------------------------- |
| `test-runner`        | `natelandau-toolkit` | Runs the project's linters and tests, and returns a pass or fail summary. |
| `review-finder`      | `natelandau-toolkit` | Examines code from one angle for `/refactor` and `/organize`.             |
| `review-verifier`    | `natelandau-toolkit` | Accepts or rejects each finding from `review-finder`, with a reason.      |
| `doc-drift-reviewer` | `natelandau-git`     | Finds docs that a branch made incorrect or incomplete.                    |

## Contributing

This is a personal project, but the internals are documented for anyone who forks it. See [CONTRIBUTING.md](CONTRIBUTING.md) for the architecture, the hook plugin contract, the tests, and how to add a component.

## License

Released under the [MIT License](LICENSE).
