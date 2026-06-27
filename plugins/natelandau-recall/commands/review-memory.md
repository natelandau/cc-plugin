---
description: Review and curate this project's persisted memory store - deduplicate learnings, prune stale entries, correct frontmatter, and close resolved backlog items.
---

## Locate the memory store

Compute the project key:

1. Run `git rev-parse --path-format=absolute --git-common-dir` from the current directory. Strip the trailing `/.git` component to get the project root. If git fails or is unavailable, fall back to `$CLAUDE_PROJECT_DIR`, then to `cwd`.
2. Dash-encode the absolute path: replace every `/` with `-` (the leading `/` becomes a leading `-`). Any path segment that starts with `.` gets its dot turned into a dash, yielding a double dash at that boundary (e.g. `/.hidden` → `--hidden`).
3. The memory directory is `$XDG_DATA_HOME/natelandau-recall/<encoded-key>/` (default `~/.local/share/natelandau-recall/<encoded-key>/` when `XDG_DATA_HOME` is unset).

If the directory does not exist, report "No memory store found for this project." and stop.

## Review each memory artifact

### `learnings/` - atomic learning files

List all files under `learnings/`. Each file is a short YAML frontmatter block followed by prose. Expected frontmatter keys: `summary` (one sentence), `read_when` (brief trigger hint), and optionally `tags`.

For each file:
- **Missing or weak frontmatter:** Fill in or sharpen `summary` and `read_when` if absent or vague.
- **Duplicates / near-duplicates:** Identify learnings that cover the same topic. Merge them into the most complete file and delete the redundant ones. This command is the only place deletion is permitted - the automated sweep never removes files.
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
