# Regrouping a branch's history: shared procedure

Repackage a feature branch's commits into fewer, logically grouped, reviewable
commits without changing the resulting code. The files on disk end up
byte-for-byte identical. Only the commit boundaries change.

The calling skill passes two values. Substitute them wherever they appear:

- `<base>`: the commit to regroup on top of. Everything in `<base>..HEAD` is
  repackaged, and `<base>` itself is untouched. A caller that already rebased
  onto the trunk passes the trunk. A caller that did not passes
  `git merge-base <trunk> HEAD`.
- `<original-tip>`: a ref or SHA at the branch tip before any rewrite, used to
  prove the tree is unchanged. A caller passes a backup branch or a SHA it
  recorded with `orig=$(git rev-parse HEAD)`.

Do every step in order, then return to the calling skill.

Every commit you make here must be a valid conventional commit:
`<type>(<scope>): <subject>`, imperative, lowercase subject, at most 70
characters, with a type from `build ci docs feat fix perf refactor style test`.
There is no `chore`. The `enforce_commit_message` hook validates each
`git commit`, and `--no-verify` does not bypass it. A malformed subject blocks
the rewrite mid-way.

## Step 1: Decide whether regrouping helps

```bash
git log --oneline <base>..HEAD   # the story the branch tells
```

There is no commit-count threshold. Judge the log. If it already reads as a
small set of commits that each describe one coherent change, report that and
return without rewriting. Regroup when the log has sprawled: many tiny edits,
`wip` or `fixup` commits, or back-and-forth corrections.

One more trigger, even on a clean log: a standalone doc commit that documents
code also changed on this branch. Step 2 folds it into that code's commit.

## Step 2: Decide the logical groups

The groups live in the diff, not in the existing commit boundaries:

```bash
git diff <base>..HEAD   # the full change, the ground truth for grouping
```

Choose a grouping in which:

- Each commit covers one area or concern.
- Documentation rides with the code it documents. A README, CHANGELOG, guide,
  or inline-doc change that explains code in this branch goes into that code's
  commit, not a standalone `docs:` commit. Docs get their own commit only when
  they stand alone.
- Commits read top to bottom: groundwork first (a refactor, a new helper, a
  schema change), then the work that builds on it.
- Each subject names what the commit does, as a valid conventional commit
  written to the bar in `commit-subjects.md` (in this directory).

Aim for a handful of commits split by area. If one file spans every concern,
do not force an artificial split. Fewer honest commits beat many contrived
ones.

## Step 3: Rebuild the history

Interactive rebase is unavailable in this environment, so rebuild with a soft
reset and re-commit by group. A soft reset moves the branch ref and leaves the
working tree and index untouched, so no commit is replayed and no conflict is
possible. The only risk is a wrong grouping, which Step 4 catches.

```bash
git reset --soft <base>   # uncommit the branch's commits; working tree untouched
git restore --staged .    # unstage everything so each group commits on its own
```

Then, in reading order, stage each group's paths and commit it with
`--no-verify`:

```bash
git add <paths for group 1>
git commit --no-verify -m "<type>(<scope>): <subject>"
# repeat for each remaining group, groundwork commits first
```

Each group stages only a slice of the tree, so a `pre-commit` hook would run
against an index that is incomplete by design: a helper without its caller, an
implementation without its test. A linter or test hook fails on the slice and
strands the branch mid-rewrite. A formatting hook rewrites files and breaks the
byte-identical check in Step 4. Neither is a real quality signal. Skip the
hooks per group and run the gate once, on the finished tree, in Step 5.

Two limits on `--no-verify`:

- Never use `git rebase --no-verify`. It skips only the `pre-rebase` hook, and
  the `enforce_branch_protection` hook blocks it. Nothing here needs it.
- Never use it on a whole-tree commit. A prep commit or a fix commit after
  Step 5 stages the full tree, so its hooks run normally.

## Step 4: Verify the tree is unchanged

Prove that nothing changed but the commit boundaries:

```bash
git diff <original-tip> HEAD --stat   # MUST be empty
git status --porcelain                # MUST be empty
```

If both are empty, continue to Step 5. If either is non-empty, content was lost
or altered. Restore and abort:

```bash
git reset --hard <original-tip>
```

Report that the rewrite was rolled back and the branch is exactly as it was.
Do not retry blindly. Re-read the diff and fix the grouping first.

## Step 5: Run the project's full gate once

Step 3 skipped the per-commit hooks. Now that the tree is whole, run the
project's real gate over all of it. Dispatch the `test-runner` subagent, or run
the gate directly (`pre-commit run --all-files` plus the project's test
command).

- Green: the rewrite is done. Return to the calling skill.
- Red: do not amend the group commits. Step 4 proved this tree is byte-for-byte
  what the branch already had, so the failure predates the rewrite. Stop,
  report the failures, state that the regrouped history is sound, and let the
  calling skill or the user decide whether to fix forward or reset to
  `<original-tip>`.
