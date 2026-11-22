---
name: squash
description: Use when the user says squash or asks for a single commit, such as to squash a branch into main or master, squash-merge it, land or merge it as one commit, or collapse the branch (or its worktree) into one commit on the trunk, even casually ("squash this into main", "squash and land it"). Local, destructive, never pushes. A plain "merge into main" means the fast-forward workflow, and opening a pull request is a different workflow.
---

# Squash

Collapse a finished feature branch (or its worktree) into one commit on the local
`main` or `master`, then clean up. Destructive and irreversible once deletions run.

## Guardrails

- Never push. Stop after cleanup; the user pushes.
- Write and commit the squash message without an approval pause; report it.
- Confirm the squash commit exists and holds the work before deleting any branch or
  worktree.
- Every commit follows the user's commit conventions. `enforce_commit_message` rejects
  a message that breaks them; fix it to the rules its block message lists.
- `enforce_branch_protection` blocks commits on `main`/`master` except during a squash
  merge (it detects `SQUASH_MSG` in the git dir, or a `git merge --squash ... && git
  commit` chain). The final commit must go through `git merge --squash` then
  `git commit`; never commit on the trunk another way.

## Steps 0 and 1: Detect and sync

Read `../shared/trunk-sync.md` (relative to this skill's base directory). Run its
Detect section, then its Sync the local trunk section. Its "Return to the trunk"
section runs in Step 4.

## Steps A to D: Prepare the branch

Read `../shared/finishing-prep.md` (relative to this skill's base directory) and do
every step. Its commits go on the feature branch. Pass `<rebase-onto>` = the local
`<trunk>` (synced in Step 1, can be ahead of the remote), not `origin/<trunk>`. Return
here when done.

## Step 4: Squash onto the trunk

Run the "Return to the trunk" section of `../shared/trunk-sync.md`.

Squash-merge:

```bash
git merge --squash <feature-branch>
```

This stages the branch's changes and writes `SQUASH_MSG`. On conflicts, stop, report
the files, and let the user resolve them (then resume at the commit). Never guess at
resolutions.

Read the branch for context:

```bash
git log --oneline <trunk>..<feature-branch>   # commits being collapsed
git diff --staged --stat                      # net change landing on the trunk
```

Write one commit summarizing the whole branch, to the user's conventions, from the
staged diff, not the intermediate commits. Commit and confirm:

```bash
git commit -m "<subject>" -m "<body>"
git log -1 --stat        # the squash commit exists and holds the work
```

If a `pre-commit` formatter rewrites the staged tree, re-stage and re-commit; the
squash is still in progress. Never `--no-verify` on this whole-tree commit.

## Step 5: Clean up

Only after the commit is confirmed. A squash records no merge ancestry, so
`git branch -d` fails "not fully merged": use `-D` (the hook protects only
`main`/`master` from force-deletion). A branch checked out in a worktree can't be
deleted, so remove the worktree first:

```bash
git worktree remove <worktree-path>   # worktree case only; never rm -rf by hand
git branch -D <feature-branch>
```

If `git worktree remove` reports untracked or dirty files, stop and show the user.
Forcing it discards their files.

## Finish

Report the squash commit (hash, subject) on the local trunk, the deleted branch, and
the removed worktree. Remind the user the trunk is not pushed.
