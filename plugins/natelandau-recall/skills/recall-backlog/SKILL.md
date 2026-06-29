---
name: recall-backlog
description: Triage and curate this project's persisted recall backlog - validate the open items against the current repo, apply the resulting fixes (close finished work, remove obsolete items, correct drifted ones), then rank what remains by impact and effort to recommend what to do next. Pass --clean to apply removals automatically instead of confirming them.
disable-model-invocation: true
argument-hint: "[--clean]"
---

# Recall Backlog

Triage this project's deferred-work backlog, clean it up, and surface what is worth
doing next. Two read-only reviewer subagents (they ship with this plugin) do the
analysis: one checks whether each open item is still real, the other scores the real
ones by value. You apply the validity fixes to `backlog.md` and then report.

You are the only writer here - the subagents never touch files. Closing a finished
item and correcting a drifted one are safe and apply directly. Removing an item
discards real deferred work if the reviewer is wrong, and the store is not under
version control, so a wrong removal cannot be rolled back - which is why removals
are gated by confidence and mode.

## Mode

Parse `$ARGUMENTS` for the token `--clean`:

- **CLEAN** - `true` if `--clean` appears anywhere, otherwise `false`.

Echo the mode back in one line before proceeding: `propose` when `CLEAN` is false,
`clean` when true, so the user knows up front whether removals will be applied for
them. The mode only changes how removals are applied (Phase 3); everything else is
the same either way.

## Locate the memory store

Resolve the store paths with the recall path resolver. It derives the project's store
for you, so never compute the key by hand:

```bash
${CLAUDE_SKILL_DIR}/../../hooks/recall-path.py --data-dir   # the store directory
${CLAUDE_SKILL_DIR}/../../hooks/recall-path.py --backlog    # backlog.md inside it
```

If the store directory or its `backlog.md` does not exist, report "No backlog found for
this project." and stop. If `backlog.md` has no open `- [ ]` items, report "The
backlog has no open items." and stop.

## Phase 1 - validate the open items

Collect every open (`- [ ]`) item from `backlog.md`. Dispatch one
`backlog-validity-reviewer` subagent **per item, in parallel**, via the `Agent`
tool. Pass each the absolute store path and the item line verbatim. Each returns
`CLOSE` (already done), `REMOVE` (obsolete), `AMEND` (drifted but real), or `KEEP`,
with cited evidence and a `confidence`.

Do this first because an item still marked `[ ]` may already be done or no longer
relevant - counting it as open work, or recommending it, would mislead the user.
Treat `KEEP` and `AMEND` items as **genuinely open**.

## Phase 2 - score the genuinely-open items

Dispatch one `backlog-opportunity-reviewer` subagent **per genuinely-open item, in
parallel**. Pass each the store path and the item line. Each returns `impact`
(high/medium/low), `effort` (S/M/L grounded in the actual code), `recommend_now`
(yes/no), and a one-line reason.

Running this only on the genuinely-open set keeps the recommendations honest and
avoids spending analysis on work that is already done.

## Phase 3 - apply the validity fixes

Turn the Phase 1 verdicts into edits to `backlog.md`:

- **`CLOSE`** - the work is already done, so delete the line. Apply directly when
  the reviewer's confidence is high; the evidence is cited and the finished work
  lives on in the repo and its history, so the line records nothing the store still
  needs. The "Changes applied" report names every closed item, so it stays visible
  for the run even though the line is gone. Unlike a `REMOVE`, this discards work
  that is verifiably done, not a task that was never started, which is why it applies
  directly rather than under the removal gate.
- **`AMEND`** - replace the line with the reviewer's corrected
  `- [ ] [S|M|L] <imperative> - <YYYY-MM-DD> [#area]` line. Apply directly; it fixes
  drift without discarding the item.
- **`REMOVE`** - this deletes the line and the deferred work it records, so it is
  gated by mode:
  - **`propose` (default):** list every removal for the user with the reviewer's
    evidence and get approval before deleting any of them.
  - **`clean`:** delete the **high-confidence** removals without asking, but still list
    and confirm each **low-confidence** removal first - those are the ones most
    likely to be wrong, and the deletion cannot be undone.
- **`KEEP`** - leave untouched.

Regardless of mode, confirm any `CLOSE`/`AMEND` the reviewer marked low confidence
rather than applying it blind.

Edit `backlog.md` in place. Do not add new items, and do not touch `learnings/` -
this skill curates the backlog only.

## Report

After applying the approved changes, print a compact, skimmable report.

### 1. Changes applied

A one-line summary of what changed - how many items closed, removed, and amended -
followed by the `CLOSE` and `REMOVE` items (with evidence), since both delete the
line and this report is the only record of them, plus anything still awaiting the
user's confirmation. If nothing changed, say so in one line.

### 2. Open backlog at a glance

A one-line count of the items still open after the fixes, then a table breaking them
down by scope (the conventional-commit section the item lives under:
`feat`/`fix`/`docs`/...) and size (`S`/`M`/`L`, with a `—` column for items that
carry no size tag):

| Scope | S | M | L | — | Total |
|-------|---|---|---|---|-------|
| feat  | 2 | 1 | 0 | 1 | 4     |
| fix   | 0 | 1 | 1 | 0 | 2     |
| **Total** | 2 | 2 | 1 | 1 | 6 |

### 3. Work on next

The still-open items where `recommend_now` is yes, ordered best-first. Lead with
quick wins - high impact at small effort - since those are the cheapest value, then
high-impact larger items. For each, give the item, its impact and effort, and the
one-line reason. If nothing clears the bar, say so plainly rather than padding the
list with low-value work.

Keep the whole report to the table and these short lists - a triage view the user
can act on at a glance, not an essay.
