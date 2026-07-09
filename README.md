# natelandau-cc-plugin

A personal [Claude Code](https://code.claude.com) marketplace containing two plugins: guardrails and workflow tooling for everyday coding, plus a project-memory system that remembers what each project taught you.

> [!WARNING]
> This is a personal toolkit, built for one developer's machine and habits. It's opinionated about tools (uv, ruff, conventional commits), workflows, and what counts as "safe." It changes whenever those habits change, often without notice and without backward compatibility. Install it to study or fork it, not as a stable dependency. Pin to a tag if you need things to stay put.

## What you get

Adding the marketplace gives you access to two plugins you can install independently.

| Plugin | What it does |
| --- | --- |
| `natelandau-toolkit` | PreToolUse and Stop hooks that block risky actions, on-demand skills, slash commands, and review subagents. |
| `natelandau-recall` | Captures durable project learnings and a deferred backlog at session boundaries, then surfaces them when a new session starts. |

## Requirements

Both plugins run their hooks as standalone Python scripts through [uv](https://docs.astral.sh/uv/), so you need a working install before either plugin does anything.

- Claude Code (the host for all components).
- `uv` on your `PATH`. The hook scripts launch with `uv run`, and uv fetches the required Python (3.14+) on first run.
- `git`. The branch-protection and memory features read repository state.

## Install

You install in two steps: register the marketplace, then install whichever plugins you want. Run these inside Claude Code.

1. Add the marketplace from GitHub:

   ```
   /plugin marketplace add natelandau/cc-plugin
   ```

2. Install one or both plugins:

   ```
   /plugin install natelandau-toolkit@natelandau-cc-plugin
   /plugin install natelandau-recall@natelandau-cc-plugin
   ```

That's it. Hooks register automatically, and skills, commands, and subagents become available right away. To confirm, run `/plugin` and check that the plugins appear as enabled.

## natelandau-toolkit

This plugin combines four kinds of components: hooks that enforce rules, skills that add knowledge or run workflows, slash commands, and subagents.

### Hooks

Hooks run automatically on every matching tool call. They block an action and explain why, so a guardrail holds even when the model would rather not. The active set depends on your profile (see [Configuration](#configuration)).

| Hook | Blocks |
| --- | --- |
| `branch-protection` | Destructive git operations (any branch), plus file edits and direct commits on `main` or `master`. Merge commits onto `main`/`master` (from `merge`/`pull`) prompt for approval rather than being blocked outright. Checks are keyed off the branch of the file or repo each action targets, so they hold no matter which directory the shell sits in. See [docs/branch-protection.md](docs/branch-protection.md) for the full allow/block/ask rules. |
| `protect-secrets` | Reading, editing, writing, or exfiltrating sensitive files like `.env` and credential stores. |
| `protect-system` | System-destructive shell commands. |
| `commit-message` | Commits and PR titles that don't follow conventional-commit format. |
| `config-protection` | Edits that weaken a linter, formatter, or typechecker config. |
| `use-uv` | Nothing. It's a non-blocking nudge toward `uv run` for Python commands. |

### Knowledge skills

These skills load on demand when your task matches. You don't invoke them by name. They give the model current, focused guidance on a tool or domain.

| Skill | Use when you're working with |
| --- | --- |
| `accessibility` | Web UI accessibility: ARIA, keyboard nav, focus, contrast, WCAG 2.2. |
| `daisyui` | daisyUI v5 and Tailwind CSS components, forms, and theming. |
| `documentation-writer` | READMEs, changelogs, guides, and other user-facing prose. |
| `explain-diff` | Understanding a code change, diff, branch, or PR as concepts and features rather than lines; produces an HTML explainer. |
| `flask-development` | Flask 3+ apps using the app-factory pattern and blueprints. |
| `gha` | Investigating GitHub Actions failures and finding the root cause. |
| `htmx-expert` | htmx attributes, AJAX fragments, swaps, and hypermedia patterns. |
| `nclutils` | Python projects that depend on the `nclutils` package. |
| `safe-refactoring` | Behavior-preserving refactors in any language. |
| `tortoise-orm` | Tortoise ORM v1.x models, queries, relations, and migrations. |
| `tufte-viz` | Designing or critiquing data visualizations with Tufte's principles. |
| `zensical` | Authoring docs with the Zensical static-site engine: config, admonitions, Mermaid, tabs, grids. |

### Workflow commands

These run multi-step workflows. Some are slash commands, others are skills you trigger with a slash. You invoke them deliberately; they never fire on their own. The git workflows are local-only and never push unless they say so.

| Command | What it does |
| --- | --- |
| `/refactor [--quick] [--fix] [target]` | Multi-agent review for refactor opportunities, refutes weak findings, and optionally applies the safe ones. |
| `/organize [target]` | Reviews project structure and produces a prioritized reorganization plan. Advisory only; never moves files. |
| `/prune-comments` | Reviews the current changes and cleans up their inline comments, keeping non-obvious why-comments and dropping redundant ones. Edits the working tree; never commits. |
| `/create-prd` | Generates a Product Requirements Document from the conversation. |
| `/pr` | Commits outstanding work, runs linters and tests, pushes the branch, and opens a PR with a conventional-commit title. |
| `/cleanup-branch` | Regroups the current branch's commits into fewer reviewable commits without changing the resulting code. |
| `/squash` | Squash-merges a finished branch into one commit on `main`, then deletes the branch. Irreversible. |
| `/fast-forward` | Lands a finished branch onto local `main` as a fast-forward of regrouped commits, then cleans up. Irreversible. |

### Subagents

The review commands above delegate to focused subagents that run in their own context and return a short summary. You can also call them directly when you want their narrow job done without filling the main conversation.

| Subagent | Job |
| --- | --- |
| `test-runner` | Runs the project's linters and test suite, returns a pass/fail summary. |
| `doc-drift-reviewer` | Compares user-facing docs against the current branch and lists stale or missing coverage. |
| `review-finder` | Applies one analysis angle to a scope and returns candidate findings. |
| `review-verifier` | Judges a candidate finding as kept, plausible, or refuted with a cited reason. |
| `comment-pruner` | Rewrites the inline comments in a change, keeping non-obvious why-comments and dropping the rest. Edits comments only, never code. |

## natelandau-recall

This plugin gives every project a small, persistent memory. It learns from your sessions and reminds you at the start of the next one, so hard-won context survives past a single conversation.

It works through three automatic hooks:

- When a session starts, it injects a compact summary of the project's memory: an index of learnings and a one-line pointer to the deferred backlog (a count of open items plus a nudge to run `/recall-backlog` to triage them), plus any handoff left for the next session (see [Handing off to the next session](#handing-off-to-the-next-session)).
- When a session ends, or just before the context is compacted, it spawns a background agent that reads the transcript and updates the memory store.

The sweep is conservative. It records non-obvious learnings (with rationale), durable user and project preferences and coding standards, design intent, and deferred backlog items as self-contained files in `learnings/`. It applies a strict bar: a fact earns a place only if it would help work on a *different* part of the app and could not be recovered by reading the repo, so most small sessions add little or nothing. It skips trivia, never writes secrets, and only writes inside the project's own memory directory.

### Where memory lives

Memory is stored per project, outside the repository, so it never ends up in your commits. The location follows the XDG base directory spec:

```
~/.local/share/natelandau-recall/<project-key>/
  backlog.md          deferred items grouped by commit type
  learnings/          one file per item, with a summary and "read when" hints
```

The project key is derived from the repository root, so all worktrees and branches of one repo share a single store.

### Handing off to the next session

Sometimes you want to carry an in-progress task into a fresh session, most often right before you run `/compact` or `/clear`. The automatic sweep records durable learnings, but it doesn't preserve the live details of what you're doing right now. A handoff covers that.

Run `/recall-handoff` to write a `HANDOFF.md` into the project's memory store. It captures the goal, progress so far, what worked, what to avoid, the key files, and the next steps, so a fresh session can continue where this one stopped. If a handoff already exists, the command reads it first and updates it instead of overwriting your earlier notes.

The next session picks up the handoff on its own. When a session starts from `/compact`, `/clear`, or a new launch, recall injects the handoff and then deletes it, so you get it once and it never lingers. A resumed session skips it, since that session already has the context.

The handoff lives alongside the rest of your memory in the store directory:

```
~/.local/share/natelandau-recall/<project-key>/
  HANDOFF.md          consume-once handoff for the next session
```

### Curating memory

The automated sweep only adds and refines. It never deletes. Two skills let you curate the store by hand, and they are where deletion happens.

| Command | What it does |
| --- | --- |
| `/recall-review [--clean]` | Reviews the whole store. Re-judges each learning by altitude and value, deleting entries that describe a single subsystem rather than a cross-cutting concern. Deduplicates learnings, removes stale or trivial entries, closes resolved backlog items, and fixes frontmatter. |
| `/recall-backlog [--clean]` | Triages the backlog. Validates each open item against the current repo, closes finished work, removes obsolete items, and corrects drifted ones, then ranks what remains by impact and effort to recommend what to work on next. |

Both skills delegate the judging to read-only reviewer subagents, so the per-entry analysis stays out of your main conversation. By default they apply the safe corrections directly and propose each deletion for your approval first. Pass `--clean` to apply the high-confidence deletions automatically too. Because the store isn't under version control, `--clean` still confirms any low-confidence deletion before removing it, since a wrong delete can't be undone.

### Backfilling memory from past sessions

The sweep only captures memory going forward, so a project that adopts recall after it already has history starts with an empty store. Run `/recall-bootstrap [count]` (default 20, or `--all`) to seed it from the project's past Claude Code transcripts.

The skill reads each past transcript the same way the sweep does, only your prompts and the agent's replies, never tool calls or internal reasoning, and mines them in parallel for durable learnings and deferred work. It then shows you a single proposed set of additions and writes only what you approve. Because the store isn't under version control, those writes can't be undone, so nothing is written without your confirmation.

## Configuration

Both plugins read optional TOML config files. Settings cascade: a global file applies everywhere, and a project file overrides it key by key. Every key is optional, so you can skip configuration entirely and take the defaults.

| Plugin | Global file | Project file |
| --- | --- | --- |
| `natelandau-toolkit` | `~/.claude/natelandau-toolkit.toml` | `<project>/.claude/natelandau-toolkit.toml` |
| `natelandau-recall` | `~/.claude/natelandau-recall.toml` | `<project>/.claude/natelandau-recall.toml` |

Each plugin ships a `*.toml.example` template under its `hooks/` directory. Copy it to one of the paths above and edit.

### Toolkit: profiles and disabling hooks

The toolkit groups its hooks into three profiles. `profile` selects the tier; `disabled_hooks` force-off individual hooks by id regardless of profile.

| Profile | Active hooks |
| --- | --- |
| `minimal` | branch-protection, protect-secrets, protect-system. |
| `standard` (default) | minimal plus commit-message, config-protection, use-uv. |
| `strict` | Same as standard, reserved for future use. |

```toml
# ~/.claude/natelandau-toolkit.toml
profile = "standard"
disabled_hooks = ["config-protection"]
```

You can also add project-specific blocking rules without touching the built-in ones. The protect-secrets, protect-system, and config-protection hooks read an extra rules file from `<project>/.claude/natelandau-toolkit/<hook>.rules.toml`. These rules are additive: they can add new blocks but can't weaken a built-in rule. To turn a hook off, use `disabled_hooks`. The config template documents the schema.

### Recall: injection and sweep

The recall config controls what gets injected at session start and how the end-of-session sweep behaves.

```toml
# ~/.claude/natelandau-recall.toml
[inject]
enabled = true                # set false to stop SessionStart memory injection

[sweep]
enabled = true                # set false to stop the end-of-session sweep
model = "claude-sonnet-4-6"   # model for the background sweep
min_exchanges = 10            # skip the sweep below this many real messages (user + assistant)
save_transcript = true        # save the sweep's own claude session (for API-usage auditing); false discards it
```

## Uninstalling

Remove a plugin, then the marketplace, from inside Claude Code:

```
/plugin uninstall natelandau-toolkit@natelandau-cc-plugin
/plugin uninstall natelandau-recall@natelandau-cc-plugin
/plugin marketplace remove natelandau-cc-plugin
```

Uninstalling the recall plugin leaves your stored memory in place under `~/.local/share/natelandau-recall/`. Delete that directory if you want it gone.

## Contributing

This is a personal project, but the internals are documented for anyone forking it. See [CONTRIBUTING.md](CONTRIBUTING.md) for the architecture, the hook plugin contract, testing, and how to add a component.

## License

Released under the [MIT License](LICENSE).
