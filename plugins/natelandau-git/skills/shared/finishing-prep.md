# Finishing a branch: shared preparation

The `/pull-request`, `/squash`, and `/fast-forward` skills run this preparation between
their own detection step and their own terminal step. Do every step below, in
order, then return to the calling skill.

Write every commit message here to the commit conventions in your
instructions and in the repository's own tooling, such as a commitlint or
commitizen config or CONTRIBUTING. The `enforce_commit_message` hook
validates each `git commit` against the user's configured rules, and its
block message lists the rules in force.

Every commit here stages the whole working tree with `git add -A`, so the
project's `pre-commit` hooks see a complete tree. Let them run. If a formatting
hook rewrites files and aborts the commit, re-stage and re-commit. Never use
`git commit --no-verify` in this preparation. That flag belongs only to the
partial, one-group-at-a-time commits of a history regroup.

## Step A: Commit outstanding work

The terminal step acts on committed history only.

```bash
git status --porcelain    # anything here must be committed
```

If the tree is dirty, stage and commit with a message that describes the
changes:

```bash
git add -A
git commit -m "<message>"
```

If the tree is clean, skip this step.

## Step B: Rebase onto the trunk

Bring the feature branch up to date with the trunk now, so integration
conflicts surface here instead of mid-squash or after the PR opens. You rebase
the feature branch, never the trunk. This works the same in a linked worktree.

```bash
git fetch --all --prune    # safe no-op without a remote
```

Rebase onto the ref the calling skill passed as `<rebase-onto>`:

- `/pull-request` passes `origin/<trunk>`. The PR merges into the remote trunk, and the
  fetch above refreshed it.
- `/squash` and `/fast-forward` pass the local `<trunk>` branch. The work
  lands there, and the local trunk can be ahead of the remote. The calling
  skill already fast-forwarded it to the remote before sending you here.

```bash
git rebase <rebase-onto>    # local-only repo: git rebase <trunk>
```

If the rebase reports conflicts, stop. Report which files conflict and let the
user resolve them, or run `git rebase --abort` if they prefer not to rebase now.
Do not guess at resolutions. Resume only when the rebase completes cleanly. If
the branch was already current, the rebase is a no-op.

## Step C: Fix documentation that the branch made wrong

The goal is narrow: nothing in the docs is out of date, and no major new
capability is undocumented. The docs serve a reader who uses the project, not
a changelog of the diff. Most branches need no doc change, and an empty diff
here is the common, correct outcome.

Dispatch the `doc-drift-reviewer` subagent (it ships with this plugin). It
compares the project's documentation against the branch and returns a
prioritized list of drift without editing anything. Then apply only the edits
that clear this bar, in priority order:

- Fix what is wrong. A documented command, flag, path, default, or step that
  the branch renamed, moved, removed, or changed misleads a reader today.
- Document a major new capability only if a reader looks for it: a new
  command, a new public option, a changed install step, or a prominent
  user-facing feature.
- Skip the rest. Do not add lines for internal refactors, private helpers,
  renamed internals, test changes, or minor options. When in doubt, leave it
  out.

If the `technical-writer` skill is available, use it for the writing. Commit
any documentation change on its own:

```bash
git add -A
git commit -m "<message>"
```

If the subagent is unavailable, scan the README, CONTRIBUTING, and `docs/`
yourself for anything the branch made stale.

## Step D: Get the branch green

Land only work that passes the project's own gates. This step comes after the
documentation commit so the gate runs once on the final tree, which is the
tree every later gate (a history regroup, the pre-push hook) sees. A gate whose
project caches passes by tree then skips instead of running again.

A full lint and test run produces output you do not need in this conversation,
so dispatch the `natelandau-toolkit:test-runner` subagent (it ships with the
natelandau-toolkit plugin, which this plugin depends on). It discovers the
project's tooling, modifies nothing, and returns a `GREEN` or `RED` verdict
with the failures.

- `GREEN`: move on.
- `RED`: fix what it reported, commit the fixes, and dispatch `test-runner`
  again. Repeat until green. If a fix changes behavior that Step C documented,
  update those docs in the same commit.

```bash
git add -A
git commit -m "<message>"
```

If the subagent is unavailable, discover the gates yourself from
`pyproject.toml`, `package.json`, `Makefile`, `justfile`, or the CI workflows,
and run them directly. When a project task (a `just` recipe, an npm script, a
`make` target) runs a gate, run the task rather than the tool it wraps. Do not
proceed to the terminal step with failing linters or tests.
