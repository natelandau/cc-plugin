---
name: explain-diff
description: "Use when the user wants to understand a code change, diff, branch, or PR at the level of concepts and features rather than lines: the pieces that come together to make the whole change, explained across the files they touch. Trigger on requests like \"explain this PR\", \"walk me through this branch\", \"help me understand what this change does\", \"what's going on in this diff\", or reviewing an agent's work before merging. Produces a rich, self-contained HTML explainer (plain markdown on request)."
disable-model-invocation: true
---

# Explain Diff

A diff shows which lines changed. This explains what a diff cannot: the concepts and
features that make up the change, top down, across the files they span rather than file
by file. The reader wants to understand the change, not audit it.

## 1. Resolve what to explain

The diff seeds the explanation; it does not bound it.

- PR number or URL: `gh pr diff <n>`, plus `gh pr view <n>` for title and description.
  Use the author's framing.
- Branch: `git diff <base>...HEAD` (base usually `main`).
- Commit or range: `git diff <sha>` or `git diff <a>..<b>`.
- Nothing specified: the current branch against `main`, or the uncommitted tree if that
  diff is empty. Ask if ambiguous; otherwise pick the sensible default and say which.

Then read beyond the diff: the touched files and the code that calls into or depends on
them. You can't explain how a piece fits from the piece alone.

## 2. Sections

In this order. The middle two are the heart of it.

**Background.** The existing system the change lands in: a deep background for a
newcomer, marked skippable, then a narrow one covering exactly what the change touches.

**Intuition.** The core idea in its simplest honest form, led by a concrete toy example
with small sample data. A reader who stops here leaves with the right mental model, even
if specifics stay fuzzy.

**Anatomy of the change.** Step back from files and name the two to five concepts or
features the change is made of: the units a person names when asked "what does this PR
do?" ("a new caching layer", "the retry policy", "the migration that backfills old
rows"). For each:

- Name it, say what it does and why it is here.
- Trace it across every file and hunk it touches. That spanning is what the file-by-file
  view hides.
- Show it with a small concrete example or diagram where that helps.

Close with how the pieces interlock: the data or control flow connecting them into one
change. This turns a list of parts into an understanding of the whole.

**Code walkthrough.** A lower-altitude pass for readers who want to follow the edits.
Organized by the Anatomy concepts, not by file, so it reinforces that structure. Keep it
tight.

## 3. Output format

Default: one self-contained HTML file; its diagrams and callouts are what make this
worth more than a diff. For something quick and terminal-readable, or on request for
markdown, write a plain `.md` file and skip the HTML rules.

The HTML file:

- Self-contained, inline CSS and JavaScript, no external assets.
- One long scrolling page with section headers and a table of contents. No tabs for
  top-level structure; the reader must be able to scroll and Cmd-F the whole page.
- Basic responsive styling for phones.
- Filename prefixed with today's date as `YYYY-MM-DD-`
  (`2026-07-08-explanation-<slug>.html`).
- Located outside the repo: read `../shared/output-dir.md` (relative to this skill's base
  directory) and follow it with `<kind>` = `explanations`.

Diagrams carry much of the load. Use them wherever they aid understanding, with
discipline:

- Reuse a few diagram families so the reader learns the visual language once. Two that
  earn their place: a simplified sketch of the UI the user sees (UI changes) and a system
  diagram of data flow between components. Show example data flowing through it; boxes
  with real values teach more than abstract boxes.
- Never ASCII diagrams. Build diagrams from simple HTML and CSS; use HTML lists for
  lists.
- Code blocks in `<pre>`. A styled `<div>` instead needs `white-space: pre` or
  `pre-wrap`, or the browser collapses newlines. Before saving, scan every code block
  for the whitespace rule.
- Syntax-highlight by hand (no CDN highlighter in a self-contained file). Wrap keywords,
  strings, comments, and function and type names in `<span class="tok-...">` with a
  palette of five to seven token classes in the inline `<style>`, legible on the
  code-block background, reused everywhere.
- Color diffs: added lines tinted green, removed red, with a `+`/`-` gutter; context
  neutral. Keep the tint subtle enough that highlighting stays readable.
- Callouts for key concepts, definitions, and important edge cases.

Write with the clarity and flow of Martin Kleppmann: engaging, classic plain style,
smooth transitions.

## Always pair with technical-writer

This skill covers only the explainer's mechanics: sections, the cross-cutting view, and
HTML rendering of diagrams and code. Writing quality (structure, user-focused framing,
tone, AI patterns to avoid) lives in the `technical-writer` skill. Whenever this skill is
active, invoke `technical-writer` too and follow it for the prose.
