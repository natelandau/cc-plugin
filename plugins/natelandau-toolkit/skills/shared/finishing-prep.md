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

Rebase the feature branch onto the ref the calling skill told you to use
(`<rebase-onto>`). The two callers land their work in different places, so they
sync against different refs:

- **Landing on the remote trunk** (opening a PR): `<rebase-onto>` is
  `origin/<trunk>`. The PR merges into the remote, so the remote trunk is the
  integration target. The `git fetch` above just refreshed it, so it's current.
- **Landing on the local trunk** (squashing onto local `main`): `<rebase-onto>`
  is the **local** `<trunk>` branch. The squash lands there, not on the remote,
  and the local trunk can be _ahead_ of the remote (e.g. prior unpushed squashes
  in a never-push workflow). The calling skill has already fast-forwarded the
  local trunk to its remote before sending you here, so rebasing onto it syncs
  the feature with the remote **and** those local-only commits in one step —
  surfacing any conflict here rather than mid-squash.

`git fetch` only updates remote-tracking refs (`origin/<trunk>`), never a
checked-out local branch — which is why rebasing onto `origin/<trunk>` works from
a linked worktree where the local trunk lives in another checkout, and why a
caller landing on the local trunk must bring that branch current itself first.

```bash
# Remote-backed repo: rebase onto the ref the caller specified
git rebase <rebase-onto>

# Local-only repo (no remote): rebase onto the local trunk
git rebase <trunk>
```

**If the rebase reports conflicts, stop.** Report which files conflict and let
the user resolve them (or run `git rebase --abort` if they'd rather not rebase
right now). Do not guess at resolutions — resume only once the rebase completes
cleanly. If the branch was already current, the rebase is a no-op; move on.

## Step C — Get the branch green

Land only work that passes the project's own gates. Running a full lint/test
suite produces a lot of output you don't need in this conversation, so **dispatch
the `test-runner` subagent** (ships with this plugin) to run the project's gates
and return just a `GREEN`/`RED` verdict with the specific failures. It discovers
the project's real tooling and does not modify anything.

Then:

- **`GREEN`** → nothing to fix; move on.
- **`RED`** → fix what it reported here in the main conversation, commit the
  fixes, and re-dispatch `test-runner` to confirm. Repeat until green.

```bash
git add -A
git commit -m "<type>(<scope>): <subject>"
```

If the subagent is unavailable for any reason, run the project's gates directly
(discover them from `pyproject.toml`, `package.json`, `Makefile`, CI workflows,
etc. — don't assume) and proceed the same way. **Do not proceed to the terminal
step with failing linters or tests.**

## Step D — Review and update documentation

Keep the docs in sync with what the branch changed. Reviewing every doc against
the full diff is verbose, read-only analysis, so **dispatch the
`doc-drift-reviewer` subagent** (ships with this plugin) to compare the project's
documentation against the branch's changes and return a prioritized list of drift
(stale instructions, undocumented new behavior, dangling references). It is
read-only and recommends edits without making them.

Then apply the recommended updates here, in priority order. If the
`documentation-writer` skill is available, use it for the actual writing. Commit
any documentation changes with a conventional message:

```bash
git add -A
git commit -m "<type>(<scope>): <subject>"
```

If the subagent reports no drift (or is unavailable and a quick manual scan of the
README, CONTRIBUTING, and `docs/` shows nothing stale), there's nothing to commit
— move on.
