# Finishing a branch: shared preparation

Run by `/pull-request`, `/squash`, and `/fast-forward` between their detection and
terminal steps. Do every step in order, then return to the caller.

- Commit messages follow the commit conventions in your instructions and the repo's
  tooling (commitlint, commitizen, CONTRIBUTING). The `enforce_commit_message` hook
  validates each `git commit`; its block message lists the rules in force.
- Every commit here stages the whole tree with `git add -A` so `pre-commit` hooks see a
  complete tree. Let them run. If a formatter rewrites files and aborts the commit,
  re-stage and re-commit. Never `--no-verify` here; that flag belongs only to the
  partial per-group commits of a history regroup.

## Step A: Commit outstanding work

The terminal step acts on committed history only. If `git status --porcelain` prints
anything:

```bash
git add -A
git commit -m "<message>"   # message describes the changes
```

## Step B: Rebase onto the trunk

Surfaces integration conflicts now, not mid-squash or after the PR opens. Rebase the
feature branch, never the trunk. Same in a linked worktree.

```bash
git fetch --all --prune     # safe no-op without a remote
git rebase <rebase-onto>    # local-only repo: git rebase <trunk>
```

`<rebase-onto>` comes from the caller:

- `/pull-request`: `origin/<trunk>`. The PR merges into the remote trunk, refreshed by
  the fetch.
- `/squash`, `/fast-forward`: the local `<trunk>`. The work lands there, it can be ahead
  of the remote, and the caller already fast-forwarded it to the remote.

On conflicts, stop. Report the conflicting files and let the user resolve them, or run
`git rebase --abort` if they prefer not to rebase now. Never guess at resolutions.
Resume only after a clean rebase.

## Step C: Fix documentation the branch made wrong

Narrow goal: nothing in the docs is out of date, and no major new capability is
undocumented. Docs serve a user of the project, not a changelog of the diff. Most
branches need no doc change; an empty diff here is the common, correct outcome.

Dispatch the `doc-drift-reviewer` subagent (ships with this plugin). It compares the
docs against the branch and returns a prioritized drift list without editing. Tell it
to first read the repo's own documentation rules (`CLAUDE.md`, `AGENTS.md`,
`CONTRIBUTING*`, a docs style guide) and apply them before its default bar. A stricter
repo rule (document every new option, keep a CHANGELOG current) wins.

Apply edits that clear the repo's rules, else this default bar, in priority order:

- Fix what is wrong: a documented command, flag, path, default, or step the branch
  renamed, moved, removed, or changed.
- Document a major new capability only if a reader looks for it: a new command, new
  public option, changed install step, or prominent user-facing feature.
- Skip the rest: internal refactors, private helpers, renamed internals, test changes,
  minor options. When in doubt, leave it out.

Use the `technical-writer` skill for the writing if available. Commit any doc change on
its own (`git add -A`, `git commit`).

Subagent unavailable: read the repo's documentation rules, then scan the README,
CONTRIBUTING, and `docs/` yourself for anything the branch made stale.

## Step D: Get the branch green

Land only work that passes the project's gates. Runs after the doc commit so the gate
sees the final tree, the one every later gate (regroup, pre-push hook) sees.

Don't repeat a run: if you already ran tests or linters this conversation, they passed,
and no file changed since, that gate is green. Committing files changes no files;
neither does a no-op rebase. Tests and linters count separately: if you ran only one,
run only the other, and tell `test-runner` which.

Dispatch `natelandau-toolkit:test-runner` (ships with natelandau-toolkit, a dependency)
to keep full output out of this conversation. It discovers the tooling, modifies
nothing, and returns `GREEN` or `RED` with the failures.

- `GREEN`: move on.
- `RED`: fix, commit the fixes (`git add -A`, `git commit`), and dispatch again until
  green. If a fix changes behavior Step C documented, update those docs in the same
  commit.

Subagent unavailable: discover the gates from `pyproject.toml`, `package.json`,
`Makefile`, `justfile`, or CI workflows and run them directly. When a project task (a
`just` recipe, npm script, `make` target) runs a gate, run the task, not the tool it
wraps. Never proceed to the terminal step with failing linters or tests.
