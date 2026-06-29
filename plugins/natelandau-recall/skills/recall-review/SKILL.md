---
name: recall-review
description: Review and curate this project's persisted memory store - deduplicate learnings, prune stale entries, correct frontmatter, and close resolved backlog items. Pass --clean to apply the changes automatically instead of proposing them.
disable-model-invocation: true
argument-hint: "[--clean]"
---

# Recall Review

Manually curate this project's persisted memory store. Deletion happens only in
deliberate, user-invoked curation like this - the automated sweep that writes the
store only adds and refines - so periodic curation keeps it at the right altitude
and free of stale or redundant entries.

You orchestrate read-only reviewer subagents (they ship with this plugin), collect
their verdicts, then turn them into edits. The subagents never touch files; **you**
are the only writer.

## Mode

Parse `$ARGUMENTS` for the token `--clean`:

- **CLEAN** - `true` if `--clean` appears anywhere, otherwise `false`.

Echo the mode back in one line before proceeding: `propose` when `CLEAN` is false,
`clean` when true, so the user knows up front whether changes will be applied for
them. The mode only changes the apply step at the end; the review itself is the
same either way.

## Locate the memory store

Resolve the store directory with the recall path resolver. It derives the project's
store for you, so never compute the key by hand:

```bash
${CLAUDE_SKILL_DIR}/../../hooks/recall-path.py --data-dir
```

If the directory does not exist, report "No memory store found for this project." and stop.

## Health lint (deterministic, do this yourself)

Before dispatching any subagent, fix or flag the mechanical problems that need no
judgment. Read each artifact and check:

- **Learnings frontmatter:** the engine indexes on `summary`, and a learning
  lacking it is silently dropped from the SessionStart injection. If a file uses
  `name:`/`description:` instead, rename them to `summary:` (keep `read_when:`).
  Fill in or sharpen a `summary`/`read_when` that is absent or vague.
- **Malformed backlog lines:** note any item that does not match
  `- [ ] [S|M|L] <text> - <YYYY-MM-DD> [#area]` so it can be corrected.

## Dispatch the reviewers

Identify the entries to review (list `learnings/*.md`, collect the open `[ ]`
backlog items), then dispatch these read-only subagents **in parallel** via the
`Agent` tool. **Pass each one the absolute store directory path** so it reads the
entry itself, and name which entry to judge by filename or item line. Each runs in
its own context and returns a structured verdict.

- **`memory-entry-reviewer`** - one per `learnings/*.md` file. Pass the store path
  and the learning filename to judge. It returns a verdict
  (`KEEP`/`UPDATE`/`DELETE`) with gate findings, a cited reason, any
  `proposed_change`, a `confidence`, and a `backlog_candidate` flagging a learning
  that really names deferred work belonging in `backlog.md`.
- **`backlog-validity-reviewer`** - one per **open** (`[ ]`) backlog item. Pass the
  store path and the item line verbatim. It returns `CLOSE`/`REMOVE`/`AMEND`/`KEEP`
  with cited evidence, any `proposed_change`, and a `confidence`.
- **`redundancy-reviewer`** - once, over all learnings. Pass the store path; it reads
  every `learnings/*.md` itself. It returns clusters of overlapping entries to merge,
  each naming a `merge_target`; an empty list means none.

The subagents read the store by path and the repo for grounding. A single backlog
line is not addressable by path, so name it explicitly when you dispatch - the agent
still has the store path for surrounding context.

This skill curates; it does not surface new work. The `backlog-opportunity-reviewer`
agent that ships with this plugin is for other workflows - do not dispatch it here.

## Apply changes

Collect the verdicts into a concrete change set:

- **Merges** (from `redundancy-reviewer`): fold each cluster into its `merge_target`
  and delete the others.
- **Learnings** (from `memory-entry-reviewer`): `UPDATE` rewrites the text in place;
  `DELETE` removes the file; `KEEP` does nothing.
- **Backlog** (from `backlog-validity-reviewer`): `CLOSE` checks the item off as
  `[x]`, `REMOVE` deletes the line, `AMEND` replaces it with the corrected line,
  `KEEP` does nothing.
- **Backlog routing** (from each `memory-entry-reviewer`'s `backlog_candidate`): the
  sweep sometimes files concrete deferred work as a learning, so route it to the
  store that fits. For every learning flagged `needed: yes`:
  1. **Dedupe first.** Read the open `- [ ]` items and skip the add if one already
     records this fix - relocate work, never duplicate it.
  2. **Add the item** when it is absent: append a
     `- [ ] [S|M|L] <item> - <YYYY-MM-DD> [#area]` line (the same format the health
     lint checks) under the candidate's conventional-commit `section`, using today's
     date and creating the section heading if it does not exist. This is additive, so
     it applies directly in either mode.
  3. **Honor the learning role.** A `workaround` learning stays - its own
     `KEEP`/`UPDATE` verdict already governs it. A `superseded` learning is now
     redundant with the item just filed, so its verdict will be `DELETE`; remove it
     as a destructive change, gated by confidence and mode exactly like any other
     `DELETE` below.

  This is the one case where the review adds a backlog item. It is not surfacing new
  work - it is moving captured work to the correct store - so the
  `backlog-opportunity-reviewer` rule above still stands.

A change is **destructive** if it discards content with no undo: a `DELETE`, a
`REMOVE`, or the deletion of the non-target files in a merge. The store is not under
version control, so a wrong destructive change cannot be rolled back - which is why
confidence and mode gate how freely you apply them. Everything else (`UPDATE`,
`AMEND`, `CLOSE`, and the mechanical health-lint fixes like a `name:`→`summary:`
rename) rewrites content and applies directly in either mode.

How the destructive changes are applied depends on the mode:

- **`propose` (default):** present the full destructive change set to the user,
  ordered by `confidence` so the clear cases stand out, and apply only the ones they
  approve.
- **`clean`:** apply **high-confidence** destructive changes without asking. Still
  pause and confirm each **low-confidence** destructive change before applying it -
  those are the ones most likely to be wrong, and they cannot be undone.

## Report

After applying the changes, print a concise summary of what actually changed (and,
in `clean` mode, anything still awaiting the user's confirmation):

- Number of learning files reviewed, merged, and deleted.
- Whether `backlog.md` was updated (how many items closed, removed, amended, or
  routed in from a learning - and for routed items, whether the source learning was
  kept as a workaround or deleted as superseded).
- Any frontmatter corrections made.

Keep the report to one short paragraph or a brief bulleted list.
