---
name: fast-forward
description: Use when the user asks to merge a finished branch into main or master, fast-forward main, land the branch on the trunk, or bring main up to date with the branch (or its worktree). A plain "merge into main" or "merge this branch" request means this skill even when the user never says "fast-forward"; only the explicit words squash or single commit mean the squash workflow instead. Commits any outstanding work, syncs and rebases onto the local trunk, regroups the history into a few reviewable commits whose messages read as public changelog entries, fast-forwards them onto the trunk with no merge commit, then deletes the branch and removes its worktree. Local only; never pushes. Irreversible and destructive. Do not use to open a pull request.
---

# Fast-forward

Land a finished feature branch (or its worktree) on the local `main` or `master` as a
fast-forward: commits move over unchanged, no merge commit, no squash. They become the
trunk's permanent public history, so each must read as a changelog entry. Destructive
and irreversible once deletions run.

## Guardrails

- Never push. Stop after cleanup; the user pushes.
- Fast-forward only (`git merge --ff-only`). If it refuses, the trunk moved since the
  prep rebase: stop and report. Never fall back to `--no-ff`; a merge commit defeats
  the linear history.
- Every landing commit is changelog-worthy (Step 4).
- Confirm the trunk fast-forwarded and holds the work before removing any branch or
  worktree.
- Every commit follows the user's commit conventions. `enforce_commit_message` rejects
  a message that breaks them; fix it to the rules its block message lists.
  `--no-verify` does not bypass it.
- `enforce_branch_protection` blocks commits and file edits on `main`/`master`. This
  skill never trips it: every commit lands on the checked-out feature branch, and
  `git merge --ff-only` advances the trunk ref without writing a commit. A bare
  `git merge` or `--no-ff` writes a merge commit, which the hook holds for approval.

## Step 0: Detect the situation

```bash
git branch --show-current       # the feature branch
git rev-parse --git-dir         # differs from the next line inside a worktree
git rev-parse --git-common-dir  # the real .git
git worktree list               # every checkout and its branch
```

- Trunk: `main`, or `master` if that is the one that exists (`git rev-parse --verify main`).
- Layout: if `--git-dir` and `--git-common-dir` differ, you are in a linked worktree;
  the trunk is the checkout on the trunk in `git worktree list`. No checkout on the
  trunk: stop and report. Otherwise it is a single checkout, switched to the trunk in
  Step 5.

Stop and explain if the current branch is the trunk, or if the branch has no commits
beyond the trunk and `git status --porcelain` is empty. A branch level with the trunk
but with uncommitted changes is fine: prep commits it, leaving one commit to land.

## Step 1: Sync the local trunk

The local trunk can be ahead (unpushed landings) or behind its remote. Bring it current
before prep rebases onto it, so conflicts surface during prep. Skip on a local-only
repo.

```bash
git fetch --all --prune
```

Fast-forward without rewinding a locally-ahead trunk:

- Single checkout (trunk not checked out; the tree can be dirty). Update the ref only
  when the remote is strictly ahead:

  ```bash
  ahead=$(git rev-list --count origin/<trunk>..<trunk>)    # local-only commits
  behind=$(git rev-list --count <trunk>..origin/<trunk>)   # remote-only commits
  if [ "$behind" -gt 0 ] && [ "$ahead" -gt 0 ]; then
      echo "DIVERGED: both sides have unique commits"      # STOP and report, never force
  elif [ "$behind" -gt 0 ]; then
      git fetch . origin/<trunk>:<trunk>                   # remote strictly ahead: fast-forward
  fi
  # ahead-only or equal: nothing to do
  ```

- Worktree (trunk checked out elsewhere). Fast-forward in place:

  ```bash
  git -C <trunk-checkout> merge --ff-only origin/<trunk>   # diverged: fails, so stop
  ```

On divergence, stop and report. Never force the trunk to either side.

## Steps A to D: Prepare the branch

Read `../shared/finishing-prep.md` (relative to this skill's base directory) and do
every step. Its commits go on the feature branch. Pass `<rebase-onto>` = the local
`<trunk>` (synced in Step 1), not `origin/<trunk>`. That makes the feature a linear
descendant of the exact commit it lands on, which guarantees the Step 5 fast-forward.
Return here when done.

## Step 4: Regroup into changelog-worthy commits

```bash
orig=$(git rev-parse HEAD)   # pre-rewrite tip, for the byte-identical check
```

Read `../shared/regroup-history.md` (relative to this skill's base directory) and do
every step, with `<base>` = the local `<trunk>` (from Step B) and `<original-tip>` =
`$orig`. Two additions:

1. Rewrite when any message breaks the user's commit conventions, even if the grouping
   is already clean. The rewrite stays tree-preserving; only messages change.
2. Write every subject and body to those conventions.

If the closing gate is red, stop and report; do not land and do not amend the group
commits. If the procedure rolled back, the branch is unchanged: re-read the diff and
regroup again before continuing.

## Step 5: Fast-forward onto the trunk

Get onto the trunk checkout:

- Single checkout: `git checkout <trunk>`.
- Worktree: `cd` into the trunk's checkout. If `git status` shows a dirty tree, stop
  and ask the user.

Remote-backed repo: confirm the trunk is still current.

```bash
git merge --ff-only origin/<trunk>    # expected: "Already up to date"
```

Behind or diverged means the remote moved since Step 1: stop, report, restart from
Step 1.

Every repo, local-only included:

```bash
git merge-base --is-ancestor <trunk> <feature-branch>   # exit 0: still rebased on the trunk
```

Non-zero means the local trunk moved since Step B (for example, another worktree
landed work). Stop, report, and restart from Step 1 so the feature rebases onto the
current trunk.

```bash
git merge --ff-only <feature-branch>
```

Success writes no commit; the trunk ref advances to the feature tip. If it refuses
("Not possible to fast-forward"), the trunk moved since Step B: stop, report, restart
from Step 1. Never retry with `--no-ff`.

## Step 6: Verify, then clean up

```bash
git log -1 --stat                       # the feature tip is now the trunk tip
git rev-parse HEAD <feature-branch>     # both SHAs identical
```

The branch is now an ancestor of the trunk, so the safe `git branch -d` succeeds and
doubles as a final merge check. If it says "not fully merged", the merge did not land:
stop, never `-D`, and find out why the trunk tip is not the feature tip. A branch
checked out in a worktree can't be deleted, so remove the worktree first:

```bash
git worktree remove <worktree-path>   # worktree case only; never rm -rf by hand
git branch -d <feature-branch>
```

If `git worktree remove` reports untracked or dirty files, stop and show the user.
Forcing it discards their files.

## Finish

Report the commits now on the local trunk (`git log <old-trunk-tip>..HEAD --oneline`),
the deleted branch, and the removed worktree. Remind the user the trunk is not pushed.
