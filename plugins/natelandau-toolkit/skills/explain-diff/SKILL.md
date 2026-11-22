---
name: explain-diff
description: "Use when the user wants to understand a code change, diff, branch, or PR at the level of concepts and features rather than lines. Trigger on \"explain this PR\", \"walk me through this branch\", \"help me understand what this change does\", \"what's going on in this diff\", or reviewing an agent's work before merging."
disable-model-invocation: true
---

# Explain Diff

Explain the concepts and features that make up a change, top down, across the files
they span rather than file by file. The reader wants to understand the change, not
audit it.

Invoke the `technical-writer` skill too and follow it for the prose. This skill covers
only structure and rendering.

## 1. Resolve what to explain

- PR number or URL: `gh pr diff <n>`, plus `gh pr view <n>` for title and description.
  Use the author's framing.
- Branch: `git diff <base>...HEAD` (base usually `main`).
- Commit or range: `git diff <sha>` or `git diff <a>..<b>`.
- Nothing specified: the current branch against `main`; if that diff is empty, the
  uncommitted tree. Ambiguous: ask. Otherwise pick the default and say which.

The diff seeds the explanation, not its bounds. Read the touched files and the code
that calls into or depends on them.

## 2. Sections

In this order:

**Background.** The existing system the change lands in: a deep background for a
newcomer, marked skippable, then a narrow one covering exactly what the change touches.

**Intuition.** The core idea in its simplest honest form, led by a concrete toy example
with small sample data. A reader who stops here has the right mental model.

**Anatomy of the change.** Name the two to five concepts or features the change is made
of: the units a person names when asked "what does this PR do?" ("a new caching layer",
"the retry policy", "the migration that backfills old rows"). For each:

- Name it; say what it does and why it is here.
- Trace it across every file and hunk it touches.
- Show it with a small concrete example or diagram where that helps.

Close with how the pieces interlock: the data or control flow connecting them.

**Code walkthrough.** A tight, lower-altitude pass through the edits, organized by the
Anatomy concepts, not by file.

## 3. Output format

Default: one self-contained HTML file. Markdown instead when the user asks for it or
for something quick and terminal-readable: write a plain `.md` file and skip the HTML
rules.

HTML file:

- Inline CSS and JavaScript, no external assets.
- One long scrolling page with section headers and a table of contents. No tabs for
  top-level structure; the reader must be able to scroll and Cmd-F the whole page.
- Basic responsive styling for phones.
- Filename `YYYY-MM-DD-explanation-<slug>.html`, today's date.
- Location outside the repo: read `../shared/output-dir.md` (relative to this skill's
  base directory) and follow it with `<kind>` = `explanations`.

Diagrams, wherever they aid understanding:

- Reuse a few diagram families so the reader learns the visual language once. Two that
  earn their place: a simplified sketch of the UI the user sees (UI changes) and a
  system diagram of data flow between components. Show example data flowing through
  it; boxes with real values teach more than abstract boxes.
- Build from simple HTML and CSS, never ASCII. HTML lists for lists.
- Code blocks in `<pre>`. A styled `<div>` instead needs `white-space: pre` or
  `pre-wrap`, or the browser collapses newlines. Before saving, check every code block
  for this.
- Syntax-highlight by hand: wrap keywords, strings, comments, and function and type
  names in `<span class="tok-...">`, with five to seven token classes in the inline
  `<style>`, legible on the code-block background, reused everywhere.
- Diffs: added lines tinted green, removed red, with a `+`/`-` gutter; context neutral.
  Tint subtle enough that highlighting stays readable.
- Callouts for key concepts, definitions, and important edge cases.

Write with the clarity and flow of Martin Kleppmann: engaging, classic plain style,
smooth transitions.
