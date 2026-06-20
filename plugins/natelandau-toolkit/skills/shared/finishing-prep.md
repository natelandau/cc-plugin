# Finishing a branch — shared preparation

Shared by the `/pr` and `/squash` skills. Both run this identical preparation
between their own **Step 0** (detect the situation / refuse early) and their own
**terminal step** (open the PR, or squash onto the trunk). Whichever skill sent
you here: do every step below, in order, then return to that skill's terminal
step.

## Conventional commits throughout

Every commit you make here must be a valid conventional commit:
`<type>(<scope>): <subject>` — imperative, lowercase subject, ≤70-char header,
type from the allowed set (`build ci docs feat fix perf refactor style test` —
note there is no `chore`). The `enforce_commit_message` hook rejects anything
else.

## Step A — Commit outstanding work

The terminal step only acts on _committed_ history, so any uncommitted work must
be committed onto the feature branch first.

```bash
git status --porcelain    # anything here must be committed
```

If dirty, stage and commit with a conventional message describing the changes:

```bash
git add -A
git commit -m "<type>(<scope>): <subject>"
```

If the tree is already clean, skip this step.

## Step B — Sync with the latest trunk

Bring the feature branch up to date with the trunk **now**, so any integration
conflicts surface here instead of mid-squash or after the PR is open. This
matters whenever commits landed on the trunk after this branch was created.

Run this on a clean tree (Step A already committed everything). It behaves the
same in a linked worktree as in a single checkout — you rebase the _feature
branch_, never the trunk. Use the trunk / default-branch name the calling skill
established in Step 0.

```bash
git fetch --all --prune    # refresh remote-tracking refs; safe no-op without a remote
```

Rebase the feature branch onto the freshest trunk. `git fetch` only updates the
remote-tracking ref (`origin/<trunk>`), never the checked-out local branch, so
rebasing onto `origin/<trunk>` is the form that also works from a linked
worktree where the local trunk is checked out elsewhere:

```bash
# Remote-backed repo: rebase onto the freshly fetched remote trunk
git rebase origin/<trunk>

# Local-only repo (no remote): rebase onto the local trunk
git rebase <trunk>
```

**If the rebase reports conflicts, stop.** Report which files conflict and let
the user resolve them (or run `git rebase --abort` if they'd rather not rebase
right now). Do not guess at resolutions — resume only once the rebase completes
cleanly. If the branch was already current, the rebase is a no-op; move on.

## Step C — Get the branch green

Land only work that passes the project's own gates. Run every linter and test
suite the project defines, fix whatever they flag, and commit the fixes onto the
feature branch.

```bash
# Use the project's actual tooling — discover it, don't assume. For this repo:
uv run ruff check . && uv run ruff format . && uv run ty check
uv run pytest
```

Other projects may use `npm test`, `make lint`, `pre-commit run --all-files`,
etc. — read the repo's config (`pyproject.toml`, `package.json`, `Makefile`,
CI workflows) to find the real commands rather than guessing.

If anything fails, fix it and re-run until clean. Then commit the cleanup with a
conventional message:

```bash
git add -A
git commit -m "<type>(<scope>): <subject>"
```

If everything already passes and nothing changed, there's nothing to commit —
move on. **Do not proceed to the terminal step with failing linters or tests.**

## Step D — Review and update documentation

Review any project documentation and make updates as needed to avoid
documentation drift. This includes the README, CONTRIBUTING, and any other
documentation relevant to the changes. If the `documentation-writer` skill is
available, use it to review and update the documentation.

If you made any documentation updates, commit them with a conventional message:

```bash
git add -A
git commit -m "<type>(<scope>): <subject>"
```
