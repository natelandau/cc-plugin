---
name: prune-comments
description: Use when the user invokes /prune-comments to clean up inline code comments. With no arguments it reviews the current changes (uncommitted working-tree changes, or the branch-vs-trunk diff when the tree is clean); with arguments it reviews the named files, directories, or globs in full. Deletes redundant what-comments, tightens verbose ones, and keeps genuine why-comments, leaving noqa/type:ignore and other tooling directives untouched. Edits the working tree in place and does not commit. User-invoked only.
argument-hint: "[files, directories, or globs to review; omit for current changes]"
disable-model-invocation: true
---

# Prune comments

Clean up the inline comments in the work you have in flight so every survivor
earns its place: it explains a non-obvious *why* rather than restating *what*,
states a present-tense invariant instead of citing the incident or review that
motivated the change, and says it in the fewest words that still carry the
reason. Reach for it any time you want to tidy a change's comments, for example
right before you commit, or point it at any part of the codebase by naming a
scope when you invoke it.

It edits the working tree in place and stops there. Committing is yours to do, so
you can review the edits with `git diff` first.

## What it does

1. **Resolve the scope.**

   **If the invocation carried arguments** (they arrive as an `ARGUMENTS:` line
   after these instructions), that is the scope. The user is naming files,
   directories, or globs, literally (`src/api/routes.py`, `hooks/*.py`) or in
   words ("all files within src/api", "the recall engine"). Expand what they
   named to a concrete file list and review **every comment in those files**,
   not just changed lines. If nothing matches what they named, say so and stop
   rather than guessing at a different scope.

   **With no arguments**, the scope is the work in flight. Look at the working
   tree, then pick the scope that actually holds it:

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
   work. Tell it the exact scope you resolved above, and which kind it is: a
   diff range (touch only comments on changed lines) or an explicit file list
   (review every comment in each file). It reads the scope and edits comments
   in place, deleting redundant what-comments, tightening verbose ones,
   rewording history-citing ones to the present-tense reason, keeping genuine
   why-comments, and never touching
   `noqa`/`type: ignore` or other tooling directives. It edits comments only,
   never code or docstrings, and returns a short summary. Running it as a
   subagent keeps the verbose, file-by-file review out of this conversation.

   If the subagent is unavailable, do the pass yourself over the resolved scope:
   delete comments that restate the code or whose reason is already obvious,
   reword ones that reference the incident, conversation, or review behind the
   change into the present-tense invariant they protect, tighten wordy keepers,
   and leave tooling directives, docstrings, and commented-out code untouched.

3. **Report and stop.** Relay the subagent's summary: how many comments it
   removed, reworded, and left, and which files it changed. Do **not** stage or
   commit anything. Remind the user the edits are uncommitted, so they can review
   with `git diff` and commit when ready (comment-only edits fit the `style`
   conventional-commit type).
