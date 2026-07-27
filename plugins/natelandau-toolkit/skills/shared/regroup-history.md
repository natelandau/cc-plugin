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
`git commit`, so a malformed subject blocks the rewrite mid-way. This holds even
though Step 3 commits with `--no-verify`: that flag bypasses git's own hooks, not
the `enforce_commit_message` gate.

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

One more trigger, even on an otherwise-clean log: a **standalone doc commit that
documents code also changed on this branch** (typically one a docs-fix prep step
just produced) is itself a reason to regroup, so Step 2 can fold it into that
code's commit instead of leaving it to land on its own. Don't short-circuit when
such a commit is present.

## Step 2 — Decide the logical groups

Read the whole change — the groups live in the diff, not the existing commit
boundaries:

```bash
git diff <base>..HEAD   # the full change — ground truth for grouping
```

Decide a grouping such that:

- **each commit covers one area or concern** — a reviewer reads one self-contained
  commit per topic, not related edits scattered across many commits;
- **documentation rides with the code it documents** — when a doc change (README,
  CHANGELOG, guide, inline docs) explains a code change that is also in this branch,
  group it into that change's commit rather than a standalone `docs:` commit, so the
  behavior and its documentation land together. Give docs their own commit only when
  they stand alone (documenting something outside this branch, or a docs-only branch);
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

Then, in the intended reading order, stage just each group's paths and commit it.
**Every group commit takes `--no-verify`:**

```bash
git add <paths for group 1>
git commit --no-verify -m "<type>(<scope>): <subject>"
# repeat for each remaining group, groundwork commits first
```

Each group stages only a slice of the tree, so a repo with git `pre-commit` hooks
would run them against an index that is deliberately incomplete: a helper without
its caller, an implementation without its test. That breaks the rewrite two ways:

- a linter or test suite fails on the slice and aborts the commit, stranding the
  branch mid-rewrite with its history already soft-reset away;
- a formatting hook _succeeds_ by rewriting files, which changes the tree and
  makes Step 4's byte-identical check fail, rolling the whole rewrite back.

Neither is a real quality signal. The complete tree was already whatever it was
before you started. Skip the hooks per commit and run the gate once, on the
finished tree, in Step 5.

Two things `--no-verify` is **not**:

- **Not `git rebase --no-verify`.** That flag skips only the `pre-rebase` hook and
  does nothing for pre-commit; the `enforce_branch_protection` hook blocks it
  outright. Nothing in this procedure needs it.
- **Not a license to skip hooks on whole-tree commits.** Any commit that stages the
  full working tree (the calling skill's prep commits, a fix commit after Step 5)
  runs the hooks normally. If one rewrites files, re-stage and re-commit.

## Step 4 — Verify the tree is unchanged

The whole point is that nothing changed but the commit boundaries. Prove it
before reporting success:

```bash
git diff <original-tip> HEAD --stat   # MUST be empty
git status --porcelain                # MUST be empty (clean tree, everything committed)
```

- **Both empty** → the regrouping is faithful. Continue to Step 5.
- **Either is non-empty** → content was lost or altered. **Restore and abort:**

  ```bash
  git reset --hard <original-tip>
  ```

  Report that the rewrite was rolled back and the branch is exactly as it was.
  Do not retry blindly — re-read the diff and fix the grouping before another
  attempt.

## Step 5 — Run the project's full gate once

Step 3 skipped the per-commit hooks; it did not waive them. Now that the tree is
whole again, run the project's real gate over all of it. Dispatch the
`test-runner` subagent (it discovers the project's own tooling and returns just a
`GREEN`/`RED` verdict), or run the gate directly (`pre-commit run --all-files`
plus the project's test command, or whatever `pyproject.toml` / `package.json` /
`Makefile` / CI defines).

- **Green** → the rewrite is done. Return to the calling skill.
- **Red** → **do not amend the group commits to fix it.** Step 4 just proved this
  tree is byte-for-byte what the branch already had, so the failure is
  pre-existing, not something the rewrite introduced; editing files now would
  discard that proof. Stop, report the failures and the fact that the regrouped
  history itself is sound, and let the calling skill or the user decide whether to
  fix forward on top or reset to `<original-tip>`.
