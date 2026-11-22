---
name: fast-forward
description: Use when the user asks to merge a finished branch (or its worktree) into main or master, fast-forward main, land the branch on the trunk, or bring main up to date with the branch. A plain "merge into main" or "merge this branch" means this skill even without the word fast-forward; only the explicit words squash or single commit mean the squash workflow. Local, destructive, never pushes. Not for opening a pull request.
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

## Steps 0 and 1: Detect and sync

Read `../shared/trunk-sync.md` (relative to this skill's base directory). Run its
Detect section, then its Sync the local trunk section. Its "Return to the trunk"
section runs in Step 5.

## Steps A to D: Prepare the branch

Read `../shared/finishing-prep.md` (relative to this skill's base directory) and do
every step. Its commits go on the feature branch. Pass `<rebase-onto>` = the local
`<trunk>` (synced in Step 1, can be ahead of the remote), not `origin/<trunk>`. That
makes the feature a linear descendant of the commit it lands on, so Step 5 can
fast-forward.
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

Run the "Return to the trunk" section of `../shared/trunk-sync.md`.

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
