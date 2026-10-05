---
name: explain-diff
description: "Use when the user wants to understand a code change, diff, branch, or PR at the level of concepts and features rather than lines — the pieces that come together to make the whole change, explained across the files they touch. Trigger on requests like \"explain this PR\", \"walk me through this branch\", \"help me understand what this change does\", \"what's going on in this diff\", or reviewing an agent's work before merging. Produces a rich, self-contained HTML explainer (plain markdown on request)."
---

# Explain Diff

A git diff shows what lines changed. This skill produces what a diff cannot.
It explains the concepts and features that make up the change, top down,
across the files they span rather than file by file. The reader wants to
understand the change, not audit it.

## 1. Resolve what to explain

The diff is the seed of the explanation, not its boundary. First decide which
change:

- A PR number or URL: `gh pr diff <n>`, plus `gh pr view <n>` for the title
  and description. Use the author's own framing.
- A branch: `git diff <base>...HEAD`, where the base is usually `main`.
- A commit or range: `git diff <sha>` or `git diff <a>..<b>`.
- Nothing specified: the current branch against `main`, or the uncommitted
  working tree if that diff is empty. If the choice is ambiguous, ask.
  Otherwise pick the sensible default and say which you chose.

Then read beyond the diff: the files it touches and the code that calls into
or depends on them. You cannot explain how a piece fits from the piece alone.

## 2. Sections

Write these sections in this order. The middle two are the heart of the skill.

**Background.** Explain the existing system the change lands in. Give a deep
background for a newcomer, marked as skippable, then a narrower background
that covers exactly the parts the change touches.

**Intuition.** The core idea in its simplest honest form. Lead with a concrete
toy example and small sample data. A reader who stops here must leave with the
right mental model, even if the specifics stay fuzzy.

**Anatomy of the change.** Step back from the files and identify the two to
five concepts or features the change is made of. These are the units a person
names when asked "what does this PR do?", such as "a new caching layer", "the
retry policy", or "the migration that backfills old rows". For each one:

- Name it, say what it does, and say why it is here.
- Trace it across every file and hunk it touches. One feature usually spans
  several files, and that spanning is what the file-by-file view hides.
- Show it with a small concrete example or diagram where that helps.

Close the section with how the pieces interlock: the data or control flow that
connects them into one change. This wrap-up turns a list of parts into an
understanding of the whole.

**Code walkthrough.** A lower-altitude pass for readers who want to follow the
edits. Organize it by the concepts from the Anatomy section, not by file, so it
reinforces the structure you built. Keep it tight.

## 3. Output format

Default to a single self-contained HTML file. The diagrams and callouts below
are what make this worth more than a diff. If the reader wants something quick
and terminal-readable, or asks for markdown, write a plain `.md` file and skip
the HTML-specific rules.

The HTML file:

- One self-contained file with inline CSS and JavaScript. No external assets.
- One long scrolling page with section headers and a table of contents. Do
  not use tabs for the top-level structure. The reader must be able to scroll
  the whole page and search it with Cmd-F.
- Basic responsive styling, so it reads on a phone.
- A filename that starts with today's date as `YYYY-MM-DD-`, so the files sort
  by time. Example: `.agent/explanations/2026-07-08-explanation-<slug>.html`.
- A gitignored location, so the file never lands in version control. Read
  `../shared/agent-output-dir.md` (relative to this skill's base directory) and
  follow it with `<kind>` set to `explanations`.

Diagrams carry much of the load. Use them wherever they aid understanding, with
discipline:

- Pick a small number of diagram families and reuse them, so the reader learns
  your visual language once. Two that earn their place: a simplified sketch of
  the UI the user sees (for UI changes), and a system diagram of data flow
  between components. Show example data flowing through the system diagram.
  Boxes with real values teach more than abstract boxes.
- Never use ASCII diagrams. Build diagrams from simple HTML and CSS, and use
  HTML lists for lists.
- Use `<pre>` tags for code blocks. If you use a styled `<div>` instead, its
  CSS must include `white-space: pre` or `pre-wrap`, or the browser collapses
  every newline. Before you save, scan each code block and confirm that the
  whitespace rule is present.
- Syntax-highlight the code. The file is self-contained, so no CDN highlighter
  is available. Hand-highlight instead, which you can do accurately because
  you understand the code. Wrap keywords, strings, comments, and function and
  type names in `<span class="tok-...">`, and define a palette of five to
  seven token classes in the inline `<style>`. Pick colors that stay legible
  on the code-block background, and reuse the same classes everywhere.
- Color the diff. When you show a before-and-after or a hunk, tint added lines
  green and removed lines red with a `+` or `-` gutter, and leave context
  lines neutral. Keep the tint subtle enough that the syntax highlighting on
  top of it stays readable.
- Use callouts for key concepts, definitions, and important edge cases.

Write with the clarity and flow of Martin Kleppmann: engaging, in a classic
plain style, with smooth transitions between sections.

## Always pair with technical-writer

This skill covers only the mechanics of the explainer: which sections to build,
how to structure the cross-cutting view, and how to render diagrams and code in
HTML. Writing quality (clear structure, user-focused framing, tone, and the AI
writing patterns to avoid) lives in the `technical-writer` skill. Whenever this
skill is active, invoke `technical-writer` as well and follow it for the prose.
