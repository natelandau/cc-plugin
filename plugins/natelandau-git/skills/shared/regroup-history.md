# Regrouping a branch's history: shared procedure

Repackage a feature branch's commits into fewer, logically grouped, reviewable commits.
Files on disk end up byte-for-byte identical; only commit boundaries change.

The caller passes two values:

- `<base>`: the commit to regroup on. `<base>..HEAD` is repackaged; `<base>` is
  untouched. A caller that rebased onto the trunk passes the trunk; one that did not
  passes `git merge-base <trunk> HEAD`.
- `<original-tip>`: a ref or SHA at the pre-rewrite tip (a backup branch, or
  `orig=$(git rev-parse HEAD)`), used to prove the tree is unchanged.

Do every step in order, then return to the caller.

Commit messages follow the commit conventions in your instructions and the repo's
tooling (commitlint, commitizen, CONTRIBUTING). The `enforce_commit_message` hook
validates each `git commit` and its block message lists the rules in force.
`--no-verify` does not bypass it, so a rejected message blocks the rewrite mid-way.

## Step 1: Decide whether regrouping helps

```bash
git log --oneline <base>..HEAD   # the story the branch tells
```

No commit-count threshold; judge the log. If it already reads as a small set of
commits, each one coherent change, report that and return without rewriting. Regroup
a sprawl: many tiny edits, `wip` or `fixup` commits, back-and-forth corrections.

Also regroup a clean log that has a standalone doc commit documenting code changed on
this branch. Step 2 folds it into that code's commit.

## Step 2: Decide the logical groups

Groups come from the diff, not the existing commit boundaries:

```bash
git diff <base>..HEAD   # ground truth for grouping
```

- One area or concern per commit.
- Docs ride with the code they document. A README, CHANGELOG, guide, or inline-doc
  change explaining code in this branch goes in that code's commit. Docs get their own
  commit only when they stand alone.
- Reading order: groundwork first (refactor, new helper, schema change), then the work
  built on it.
- Each message names what the commit does, to the conventions above.

Aim for a handful of commits split by area. If one file spans every concern, don't
force a split. Fewer honest commits beat many contrived ones.

## Step 3: Rebuild the history

Interactive rebase is unavailable, so soft-reset and re-commit by group. A soft reset
moves the branch ref and leaves the tree and index untouched: nothing replays, no
conflict is possible. The only risk is a wrong grouping, which Step 4 catches.

```bash
git reset --soft <base>   # uncommit the branch's commits; tree untouched
git restore --staged .    # unstage so each group commits on its own

# per group, in reading order, groundwork first:
git add <paths for group>
git commit --no-verify -m "<message>"
```

Why `--no-verify`: each group stages a deliberately incomplete slice (a helper without
its caller, code without its test). A lint or test hook fails on the slice and strands
the branch mid-rewrite; a formatter rewrites files and breaks Step 4's byte-identical
check. Neither is a real quality signal. Step 5 runs the gate once on the finished tree.

Limits on `--no-verify`:

- Never `git rebase --no-verify`. It skips only `pre-rebase`, and
  `enforce_branch_protection` blocks it. Nothing here needs it.
- Never on a whole-tree commit (a prep commit, a fix commit after Step 5). Its hooks
  run normally.

## Step 4: Verify the tree is unchanged

```bash
git diff <original-tip> HEAD --stat   # MUST be empty
git status --porcelain                # MUST be empty
```

Both empty: continue. Either non-empty means content was lost or altered. Restore:

```bash
git reset --hard <original-tip>
```

Report that the rewrite rolled back and the branch is exactly as it was. Don't retry
blindly; re-read the diff and fix the grouping first.

## Step 5: Run the full gate unless it just passed

Step 3 skipped per-commit hooks, so the finished tree needs one green lint and test
run. If you already ran tests or linters this conversation, they passed, and no file
changed since, that gate is green; skip it. Dispatch `natelandau-toolkit:test-runner`
for the gates that have not passed and tell it which. If it is unavailable, discover
the lint and test gates (prefer what CI runs) and run them directly.

- Green: done. Return to the caller.
- Red: never amend the group commits. Step 4 proved the tree is what the branch
  already had, so the failure predates the rewrite. Stop, report the failures, state
  that the regrouped history is sound, and let the caller or user decide: fix forward,
  or reset to `<original-tip>`.
