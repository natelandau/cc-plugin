---
name: recall-review
description: Review and curate this project's persisted memory store - deduplicate learnings, prune stale entries, correct frontmatter, and close resolved backlog items.
disable-model-invocation: true
---

# Recall Review

Manually curate this project's persisted memory store. This is the only place
deletion happens: the automated sweep only adds and refines, so periodic curation
keeps the store at the right altitude and free of stale or redundant entries.

## Locate the memory store

Compute the project key:

1. Run `git rev-parse --path-format=absolute --git-common-dir` from the current directory. Strip the trailing `/.git` component to get the project root. If git fails or is unavailable, fall back to `$CLAUDE_PROJECT_DIR`, then to `cwd`.
2. Dash-encode the absolute path: drop the leading `/`, then replace every remaining `/` with `-`. Any path segment that starts with `.` gets its dot turned into a dash, yielding a double dash at that boundary (e.g. `/repos/.hidden` → `repos--hidden`). The key never starts with a dash.
3. The memory directory is `$XDG_DATA_HOME/natelandau-recall/<encoded-key>/` (default `~/.local/share/natelandau-recall/<encoded-key>/` when `XDG_DATA_HOME` is unset).

If the directory does not exist, report "No memory store found for this project." and stop.

## Re-judge altitude and value (the curation pass)

The automated sweep captures conservatively at a high bar. You run on a stronger
model, see the whole store at once, can read the current code, and — uniquely —
are allowed to DELETE. Your job is to prune what slipped through to the wrong
altitude. For every learning and every `architecture.md` section, apply the same
two-gate test the sweep uses:

1. **Generality** — does this help work on parts of the app OTHER than the one
   that produced it? Open the referenced code: if the entry just narrates one
   subsystem's current implementation, it fails.
2. **Non-recoverability** — read the cited files. If the code, tests, types, or
   config already make this obvious, the entry is redundant. (Durable user/project
   preferences and coding standards pass this gate even when simple — they aren't
   recoverable from the code. Keep them.)

- **architecture.md altitude audit:** beyond the size check below, flag any
  section that describes a single subsystem touched in one session rather than a
  project-wide invariant, convention, preference, or design intent. Either demote
  it to a `learnings/` file (if it's a genuine trap or standard worth keeping) or
  delete it. A section survives only if it would still matter with the code it
  describes deleted.
- **Learnings that are one change described twice:** merge into a single entry,
  or delete if the fix is already encoded in a test or migration.

## Review each memory artifact

### `learnings/` - atomic learning files

List all files under `learnings/`. Each file is a short YAML frontmatter block followed by prose. Expected frontmatter keys: `summary` (one sentence) and `read_when` (a list of when-to-read trigger hints).

For each file:
- **Wrong frontmatter keys:** The engine indexes on `summary` and a learning lacking it is silently dropped from the SessionStart injection. If a file uses `name:`/`description:` instead, rename them to `summary:` (keep `read_when:`).
- **Missing or weak frontmatter:** Fill in or sharpen `summary` and `read_when` if absent or vague.
- **Duplicates / near-duplicates:** Identify learnings that cover the same topic. Merge them into the most complete file and delete the redundant ones. This skill is the only place deletion is permitted - the automated sweep never removes files.
- **Stale or incorrect entries:** Delete learnings that describe behavior that has since changed, tools that are no longer used, or facts that are demonstrably wrong.
- **Trivial entries:** Delete learnings that contain nothing an agent couldn't infer from the project's own files.

### `backlog.md`

Open and review every item. Close items with `[x]` that are clearly done based on the current project state. Remove items that are no longer relevant. Do not add new items.

### `architecture.md`

If this file exists, read it and check its byte size. Warn if it exceeds 4096 bytes (the default injection cap) - note the exact size and suggest which sections to trim to bring it under the cap. Do not truncate it automatically; flag it for the user to decide.

## Report

After completing the review, print a concise summary:

- Number of learning files reviewed, merged, and deleted.
- Whether `backlog.md` was updated (how many items closed or removed).
- Whether `architecture.md` was flagged for size.
- Any frontmatter corrections made.

Keep the report to one short paragraph or a brief bulleted list.
