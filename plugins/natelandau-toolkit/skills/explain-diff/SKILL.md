---
name: explain-diff
description: "Use when the user wants to understand a code change, diff, branch, or PR at the level of concepts and features rather than lines — the pieces that come together to make the whole change, explained across the files they touch. Trigger on requests like \"explain this PR\", \"walk me through this branch\", \"help me understand what this change does\", \"what's going on in this diff\", or reviewing an agent's work before merging. Produces a rich, self-contained HTML explainer (plain markdown on request)."
---

# Explain Diff

A git diff shows *what lines changed*. This skill produces the thing a diff can't:
a focused, top-down explanation of the **concepts and features that come
together to make the change**, told across the files they span rather than file
by file. The reader wants to understand the change, not audit it.

## 1. Resolve what to explain

The diff is the seed of the explanation, not its boundary — you'll also read the
surrounding code to explain it well. First figure out *which* change:

- A **PR number or URL** → `gh pr diff <n>` (and `gh pr view <n>` for the title
  and description — the author's own framing is a gift, use it).
- A **branch** → `git diff <base>...HEAD` (base is usually `main`).
- A **commit or range** → `git diff <sha>` or `git diff <a>..<b>`.
- Nothing specified → the current branch vs `main`, or the uncommitted working
  tree if that's empty. If it's genuinely ambiguous which the user means, ask;
  otherwise pick the sensible default and say which you chose.

Then explore beyond the diff: read the files it touches and the code that calls
into or depends on them. You can't explain how a piece fits if you've only seen
the piece.

## 2. Sections

Write these sections, in this order. The middle two are the heart of the skill.

**Background.** Explain the existing system this change lands in. You don't know
how much the reader already knows, so give a deep background for a newcomer
(clearly marked skippable for those already familiar), then a narrower background
covering exactly the parts the change touches.

**Intuition.** The core idea in its simplest honest form — the essence, not the
details. Lead with a concrete toy example and small sample data. If someone read
only this section, they should come away with the right mental model even if
they're fuzzy on specifics.

**Anatomy of the change.** This is the section a diff can't give them. Step back
from the files and identify the **2–5 concepts or features** the change is
actually made of — the units a person would name if asked "what does this PR
*do*?" (e.g. "a new caching layer," "the retry policy," "the migration that
backfills old rows"). For each one:

- Name it and say what it does and *why* it's here.
- Trace it across **every file and hunk it touches** — a single feature usually
  spans several files, and that spanning is precisely what the file-by-file view
  hides.
- Show it with a small concrete example or diagram where that helps.

Close the section by explaining **how the pieces interlock** — the data or
control flow that connects them into one coherent change. This wrap-up is what
turns a list of parts into an understanding of the whole.

**Code walkthrough.** A secondary, lower-altitude pass for readers who want to
follow the actual edits. Organize it **by the concepts from the Anatomy section,
not by file**, so it reinforces the structure you just built instead of
re-listing the diff. Keep it tight; the heavy lifting already happened above.

## 3. Output format

Default to a single self-contained **HTML** file — the rich diagrams and callouts
below are what make this worth more than a diff. If the reader would rather have
something quick and terminal-readable, or explicitly asks for markdown, write a
plain `.md` instead and skip the HTML-specific rules.

**The HTML file:**

- One self-contained file with inline CSS and JavaScript — no external assets.
- One long scrolling page with section headers and a table of contents. **Don't**
  use tabs for the top-level structure; the reader should be able to scroll the
  whole thing and search it with Cmd-F.
- Basic responsive styling so it's readable on a phone.
- Save it to a **gitignored directory so it never lands in version control**, and
  give it a filename that **starts with today's date** in `YYYY-MM-DD-` format,
  which keeps these files time-sorted. Choose the location in this order:
  1. Prefer a `.agent/explanations/` directory inside the repo — `.agent/` is the
     conventional scratch dir. Create the `explanations/` subdir if needed.
  2. Before writing there, **confirm the path is actually ignored** with
     `git check-ignore -q .agent/explanations` (exit 0 = ignored). This matters:
     a repo where `.agent/` isn't gitignored would otherwise stage a large HTML
     file for commit. If it isn't ignored, either add `.agent/` to `.gitignore`
     first, or fall back to the next option.
  3. If there's no repo, or you can't get a gitignored path inside it, write to a
     temp dir outside the repo instead (e.g. the system temp directory).

  Example: `.agent/explanations/2026-07-08-explanation-<slug>.html`.

**Diagrams** carry a lot of the load — use them liberally where they aid
understanding, but be disciplined:

- Pick a **small number of diagram families and reuse them** throughout, so the
  reader learns to read your visual language once. Two that reliably earn their
  place: a simplified sketch of the UI the user sees (for UI changes), and a
  system diagram of data flow between components (**include example data flowing
  through it** — abstract boxes teach less than boxes with real values).
- **Never use ASCII diagrams.** Build diagrams from simple HTML and CSS; use HTML
  lists for lists.
- For code blocks, use `<pre>` tags. If you use a styled `<div>` instead, its CSS
  **must** include `white-space: pre` or `pre-wrap`, or the browser collapses
  every newline into one line. Before saving, scan each code block in the source
  and confirm the whitespace rule is present.
- **Syntax-highlight the code — plain monochrome code is much harder to read.**
  The file is self-contained, so you can't pull in a CDN highlighter; instead
  hand-highlight, which you can do accurately because you already understand the
  code. Wrap keywords, strings, comments, function/type names, etc. in
  `<span class="tok-...">` and define a small token palette (roughly 5–7 classes)
  in the inline `<style>`. Pick colors that stay legible on your code-block
  background, and reuse the same classes everywhere so the highlighting is
  consistent.
- **Color the diff itself.** When you show before/after or a hunk, tint added
  lines green and removed lines red (with a `+`/`-` gutter), and leave context
  lines neutral — this is a diff explainer, and the change should be visible at a
  glance, not buried in same-colored text. Keep the tint subtle enough that the
  syntax highlighting on top of it stays readable.
- Use **callouts** to set off key concepts, definitions, and important edge cases.

Write with the clarity and flow of Martin Kleppmann — engaging, in a classic
plain style, with smooth transitions between sections rather than abrupt topic
jumps.

## Always pair with documentation-writer

This skill covers only the **mechanics** of the explainer: which sections to
build, how to structure the cross-cutting view, and how to render diagrams and
code in HTML. It does not cover **writing quality** — clear structure,
user-focused framing, tone, and avoiding the AI writing patterns that erode
reader trust. That lives in the `documentation-writer` skill.

Whenever this skill is active, invoke the `documentation-writer` skill as well
and follow it for the prose. The two compose: `documentation-writer` decides what
to say and how to say it well; this skill decides how to structure and render it.
