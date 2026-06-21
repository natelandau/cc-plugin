# Regrouping a branch's history — shared procedure

Shared by skills that repackage a feature branch's commits into fewer,
logically grouped, reviewable commits **without changing the resulting code**.
The files on disk must end up byte-for-byte identical; only the commit
boundaries change.

The calling skill establishes two values and passes them to you. Substitute them
wherever they appear below:

- **`<base>`** — the commit to regroup on top of. Everything in `<base>..HEAD` is
  repackaged; `<base>` itself and everything under it is left untouched. (A caller
  that has already rebased onto the trunk passes the trunk; a caller that has not
  passes `git merge-base <trunk> HEAD`.)
- **`<original-tip>`** — a ref or SHA pointing at the branch tip _before_ any
  rewrite, used to prove the tree is unchanged. A caller may pass a backup branch
  it created, or record the SHA first with `orig=$(git rev-parse HEAD)`.

Do every step in order, then return to the calling skill's next step.

## Conventional commits throughout

Every commit you make here must be a valid conventional commit:
`<type>(<scope>): <subject>` — imperative, lowercase subject, ≤70-char header,
type from the allowed set (`build ci docs feat fix perf refactor style test` —
there is no `chore`). The `enforce_commit_message` hook validates each
`git commit`, so a malformed subject blocks the rewrite mid-way.

## Step 1 — Decide whether regrouping helps

Read how the history reads to a reviewer:

```bash
git log --oneline <base>..HEAD   # the story the branch tells
```

There is no fixed commit-count threshold; judge the log itself. If it already
reads as a small set of commits that each describe one coherent change, there is
nothing to gain — **report that and return without rewriting** (a clean eight-commit
branch does not need touching). Regroup when the log has sprawled: many tiny
edits, `wip`/`fixup` commits, or back-and-forth corrections a reviewer would have
to wade through.

## Step 2 — Decide the logical groups

Read the whole change — the groups live in the diff, not the existing commit
boundaries:

```bash
git diff <base>..HEAD   # the full change — ground truth for grouping
```

Decide a grouping such that:

- **each commit covers one area or concern** — a reviewer reads one self-contained
  commit per topic, not related edits scattered across many commits;
- **commits are ordered to read top to bottom** — groundwork first (a refactor, a
  new helper, a schema change), then the work that builds on it;
- **each commit's subject names what it does** as a valid conventional commit, so
  the log alone conveys the shape of the change.

Aim for a handful of commits split by area. Pick groupings the diff actually
supports (e.g. one commit per subsystem, or separating a refactor from the
feature that rides on it). If a clean per-area split is impossible (e.g. one file
genuinely spans every concern), do not force an artificial division — keep changes
that cannot be cleanly separated together. Fewer honest commits beat many
contrived ones.

## Step 3 — Rebuild the history

Interactive rebase (`git rebase -i`) is unavailable in this environment, so
rebuild with a soft reset and re-commit by group. A soft reset moves the branch
ref but leaves the working tree and index content untouched, so **no commit is
replayed and no merge conflict is possible** — the only risk is an incorrect
grouping, which Step 4 catches.

```bash
git reset --soft <base>   # uncommit the branch's commits; working tree untouched
git restore --staged .    # unstage everything so each group commits on its own
```

Then, in the intended reading order, stage just each group's paths and commit it:

```bash
git add <paths for group 1>
git commit -m "<type>(<scope>): <subject>"
# repeat for each remaining group, groundwork commits first
```

## Step 4 — Verify the tree is unchanged

The whole point is that nothing changed but the commit boundaries. Prove it
before reporting success:

```bash
git diff <original-tip> HEAD --stat   # MUST be empty
git status --porcelain                # MUST be empty (clean tree, everything committed)
```

- **Both empty** → the regrouping is faithful. Return to the calling skill.
- **Either is non-empty** → content was lost or altered. **Restore and abort:**

  ```bash
  git reset --hard <original-tip>
  ```

  Report that the rewrite was rolled back and the branch is exactly as it was.
  Do not retry blindly — re-read the diff and fix the grouping before another
  attempt.
