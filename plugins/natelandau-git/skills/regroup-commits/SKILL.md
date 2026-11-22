---
name: regroup-commits
description: Use when the user runs /regroup-commits to repackage the current branch's commits into fewer, logically grouped commits without changing the code. Local only; never pushes.
disable-model-invocation: true
---

# /regroup-commits

Repackage the commits the current branch adds on top of the trunk into fewer, logically
grouped, reviewable commits. Files end up byte-for-byte identical; only commit
boundaries change. Not a squash to one commit. Never fetches, rebases, pushes, or
merges.

## Guardrails

- Create a backup branch at HEAD before the first rewrite. `git reset --hard <backup>`
  restores everything.
- The tree must end byte-for-byte identical. The shared procedure enforces this and
  restores on drift.
- Refuse on a dirty tree; the guarantee covers committed history only.

## Step 0: Detect the situation

```bash
git branch --show-current                                                  # the branch
gh repo view --json defaultBranchRef -q .defaultBranchRef.name 2>/dev/null # trunk, if a remote exists
git rev-parse --verify main >/dev/null 2>&1 && echo main || echo master    # trunk fallback
git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null         # upstream, if pushed
```

- Trunk: what `gh` reports, else `main`, else `master`.
- Merge-base: `git merge-base <trunk> HEAD`. This is the regroup base, not the trunk
  tip, so the tree is preserved even if the branch was never rebased onto the latest
  trunk.
- Upstream: used for Step 4's closing note.

## Step 1: Refuse early

Stop, change nothing, and explain if:

- The current branch is the trunk.
- `git status --porcelain` prints anything. Tell the user to commit or stash; never do
  it for them.
- `git rev-list --count <merge-base>..HEAD` is 1 or less. Nothing to regroup.

## Step 2: Create the backup branch

```bash
sha7=$(git rev-parse --short HEAD)
safe=$(git branch --show-current | tr '/' '-')   # a slash would nest the ref
git branch "backup/${safe}-${sha7}"
```

If that name exists, a prior regroup ran on the same tip. Stop and ask the user to
remove the stale backup; never overwrite it.

## Step 3: Regroup

Read `../shared/regroup-history.md` (relative to this skill's base directory) and do
every step, with `<base>` = the merge-base and `<original-tip>` = the backup branch.
Then:

- Nothing to do: delete the backup (`git branch -D backup/...`), tell the user the
  branch was already tidy, and stop.
- Closing gate red: the regrouped history is sound and the failures predate it. Report
  them, keep the backup, skip Step 4's delete offer, and let the user decide. Don't fix
  the failures yourself.
- Rebuilt and green: continue.

## Step 4: Report and offer to delete the backup

Print one row per commit in `<trunk>..HEAD`, from `git log --oneline` and
`git show --stat`:

```text
New history on <branch> (<old-count> -> <new-count> commits):

  #  Commit                                       Files  +/-
  1  refactor(rules): extract shared matcher          3  +88 / -40
  2  feat(rules): add conditions operator             4  +120 / -6

Backup saved at backup/<branch>-<sha7>.
```

Ask whether to delete the backup:

- Delete: `git branch -D backup/<branch>-<sha7>`, then confirm it is gone.
- Keep: print its name for later.

If the branch has an upstream, add: local history was rewritten, so the remote needs
`git push --force-with-lease`. `enforce_branch_protection` blocks agent force pushes, so
the user runs it.
