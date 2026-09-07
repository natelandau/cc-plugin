---
name: prune-comments
description: Use when the user invokes /prune-comments to clean up inline code comments. With no arguments it reviews the current changes (uncommitted working-tree changes, or the branch-vs-trunk diff when the tree is clean); with arguments it reviews the named files, directories, or globs in full. Deletes redundant what-comments, tightens verbose ones, and keeps genuine why-comments, leaving noqa/type:ignore and other tooling directives untouched. Edits the working tree in place and does not commit. User-invoked only.
argument-hint: "[files, directories, or globs to review; omit for current changes]"
disable-model-invocation: true
---

# Prune comments

Clean up the inline comments in the work in flight, or in a named scope, so
every survivor explains a non-obvious why, states a present-tense invariant
rather than the incident that motivated it, and does so in the fewest words.
The skill edits the working tree in place and stops there. The user reviews
the edits with `git diff` and commits.

## What to do

1. Resolve the scope.

   If the invocation carried arguments (they arrive as an `ARGUMENTS:` line
   after these instructions), that is the scope. The user names files,
   directories, or globs, literally (`src/api/routes.py`, `hooks/*.py`) or in
   words ("all files within src/api"). Expand what they named to a concrete
   file list and review every comment in those files. If nothing matches,
   say so and stop rather than guess at a different scope.

   With no arguments, the scope is the work in flight:

   ```bash
   git status --porcelain     # is anything uncommitted?
   ```

   - Dirty tree: the scope is the uncommitted work, `git diff HEAD` plus any
     new untracked files.
   - Clean tree: the scope is the branch's committed changes against its
     trunk (`main`, else `master`):

     ```bash
     git merge-base <trunk> HEAD   # fork point; scope is <merge-base>..HEAD
     ```

   - Clean tree on the trunk itself: there is nothing to review. Say so and
     stop.

2. Dispatch the `comment-pruner` subagent (it ships with this plugin). Tell it
   the exact scope and which kind it is: a diff range (touch only comments on
   changed lines) or an explicit file list (review every comment in each
   file). It edits comments in place, never code or docstrings, and returns a
   short summary. Running it as a subagent keeps the file-by-file review out
   of this conversation.

   If the subagent is unavailable, do the pass yourself over the resolved
   scope. Delete comments that restate the code or whose reason is obvious.
   Reword comments that cite the incident, conversation, or review behind the
   change into the present-tense invariant they protect. Tighten wordy
   keepers. Leave tooling directives, docstrings, and commented-out code
   untouched.

3. Report and stop. Relay the summary: how many comments were removed,
   reworded, and left, and which files changed. Do not stage or commit
   anything. Remind the user that the edits are uncommitted. Comment-only
   edits fit the `style` conventional-commit type.
