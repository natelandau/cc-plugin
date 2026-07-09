---
name: prune-comments
description: Use when the user invokes /prune-comments to clean up inline code comments in the current changes. Reviews the uncommitted working-tree changes (or the branch-vs-trunk diff when the tree is clean), then deletes redundant what-comments, tightens verbose ones, and keeps genuine why-comments, leaving noqa/type:ignore and other tooling directives untouched. Edits the working tree in place and does not commit. User-invoked only.
disable-model-invocation: true
---

# Prune comments

Clean up the inline comments in the work you have in flight so they explain *why*,
not restate *what* the code already says. Reach for it any time you want to tidy a
change's comments, for example right before you commit.

It edits the working tree in place and stops there. Committing is yours to do, so
you can review the edits with `git diff` first.

## What it does

1. **Resolve what "the current changes" are.** Look at the working tree, then pick
   the scope that actually holds the work:

   ```bash
   git status --porcelain     # is anything uncommitted?
   ```

   - **Dirty tree** (uncommitted changes present): the scope is that uncommitted
     work, `git diff HEAD` plus any new untracked files. This is the common case,
     where you have been editing and want the comments cleaned before you commit.
   - **Clean tree**: fall back to the current branch's committed changes against
     its trunk. Establish the trunk (prefer `main`, else `master`) and the fork
     point, and review that range:

     ```bash
     git merge-base <trunk> HEAD   # fork point; scope is <merge-base>..HEAD
     ```

   - **Clean tree on the trunk itself** (no branch changes and nothing
     uncommitted): there is nothing to review, so say so and stop.

2. **Dispatch the `comment-pruner` subagent** (ships with this plugin) to do the
   work. Tell it the exact scope you resolved above so it reviews the right diff.
   It reads the changes and edits comments in place, deleting redundant
   what-comments, tightening verbose ones, keeping genuine why-comments, and never
   touching `noqa`/`type: ignore` or other tooling directives. It edits comments
   only, never code or docstrings, and returns a short summary. Running it as a
   subagent keeps the verbose, file-by-file review out of this conversation.

   If the subagent is unavailable, do the pass yourself over the resolved diff,
   applying the same why-not-what rule.

3. **Report and stop.** Relay the subagent's summary: how many comments it
   removed, reworded, and left, and which files it changed. Do **not** stage or
   commit anything. Remind the user the edits are uncommitted, so they can review
   with `git diff` and commit when ready (comment-only edits fit the `style`
   conventional-commit type).
