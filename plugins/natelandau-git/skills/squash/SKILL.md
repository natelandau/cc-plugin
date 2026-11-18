---
name: squash
description: Use when the user asks to squash a branch into main or master, squash-merge the branch, land or merge the branch as a single commit, or collapse the branch (or its worktree) into one commit on the trunk, even when phrased casually ("squash this into main", "squash and land it"). Commits any outstanding work, squash-merges the whole branch into one commit on the local main or master branch, then deletes the branch and removes its worktree. Local only; never pushes. This is an irreversible, destructive workflow, so reach for it only when the user says squash or asks for a single commit: a plain "merge into main" means the fast-forward workflow, and opening a pull request is a different workflow.
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
  Step 4.

Stop and explain if the current branch is the trunk, or if the branch has no commits
beyond the trunk and `git status --porcelain` is empty. A branch level with the trunk
but with uncommitted changes is fine: prep commits it, leaving one commit to squash.

## Step 1: Sync the local trunk

The local trunk can be ahead (unpushed squashes) or behind its remote. Bring it current
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

On divergence, stop and report. Never force.

## Steps A to D: Prepare the branch

Read `../shared/finishing-prep.md` (relative to this skill's base directory) and do
every step. Its commits go on the feature branch. Pass `<rebase-onto>` = the local
`<trunk>` (synced in Step 1), not `origin/<trunk>`. Return here when done.

## Step 4: Squash onto the trunk

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
landed work). The squash would commit a tree Step D never gated and could silently
undo the newer trunk work. Stop, report, restart from Step 1.

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
staged diff rather than the intermediate commits. Commit without an approval pause and
confirm:

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
