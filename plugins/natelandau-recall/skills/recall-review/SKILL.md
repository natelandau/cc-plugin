---
name: recall-review
description: Review and curate this project's persisted memory store - deduplicate learnings, prune stale entries, correct frontmatter, and close resolved backlog items. Pass --fix to apply the changes automatically instead of proposing them.
disable-model-invocation: true
argument-hint: "[--fix]"
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

Parse `$ARGUMENTS` for the token `--fix`:

- **FIX** - `true` if `--fix` appears anywhere, otherwise `false`.

Echo the mode back in one line before proceeding: `propose` when `FIX` is false,
`fix` when true, so the user knows up front whether changes will be applied for
them. The mode only changes the apply step at the end; the review itself is the
same either way.

## Locate the memory store

Compute the project key:

1. Run `git rev-parse --path-format=absolute --git-common-dir` from the current directory. Strip the trailing `/.git` component to get the project root. If git fails or is unavailable, fall back to `$CLAUDE_PROJECT_DIR`, then to `cwd`.
2. Dash-encode the absolute path: drop the leading `/`, then replace every remaining `/` with `-`. Any path segment that starts with `.` gets its dot turned into a dash, yielding a double dash at that boundary (e.g. `/repos/.hidden` → `repos--hidden`). The key never starts with a dash.
3. The memory directory is `$XDG_DATA_HOME/natelandau-recall/<encoded-key>/` (default `~/.local/share/natelandau-recall/<encoded-key>/` when `XDG_DATA_HOME` is unset).

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
  `proposed_change`, and a `confidence`.
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
  `KEEP` does nothing. Do not add new items.

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
- **`fix`:** apply **high-confidence** destructive changes without asking. Still
  pause and confirm each **low-confidence** destructive change before applying it -
  those are the ones most likely to be wrong, and they cannot be undone.

## Report

After applying the changes, print a concise summary of what actually changed (and,
in `fix` mode, anything still awaiting the user's confirmation):

- Number of learning files reviewed, merged, and deleted.
- Whether `backlog.md` was updated (how many items closed, removed, or amended).
- Any frontmatter corrections made.

Keep the report to one short paragraph or a brief bulleted list.
