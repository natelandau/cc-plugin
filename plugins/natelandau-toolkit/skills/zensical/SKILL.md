---
name: zensical
description: "Use when authoring, building, configuring, or reviewing documentation with the Zensical static-site engine. Trigger on any zensical.toml or mkdocs.yml work, running zensical new/build/serve, writing docs/ Markdown pages, or requests to make documentation richer with Mermaid diagrams, admonitions/call-outs, code annotations, content tabs, grids, or icons. Also use whenever writing Markdown that will be published with Zensical, even if the user does not say 'Zensical' by name. Actively reach for these rich elements whenever they make the docs clearer, not only when asked."
---

# Zensical documentation

Zensical is the static documentation engine from the makers of Material for
MkDocs. It turns a `docs/` folder of Markdown plus a `zensical.toml` config into
a fast, searchable, responsive site. Its value over plain Markdown is a large
library of authoring extensions: admonitions, annotated code, tabbed content,
Mermaid diagrams, grids, icons, and more. Use them.

Zensical tracks live docs and evolves quickly. If a detail here looks stale or a
build errors on a setting, check the current docs at <https://zensical.org/docs>
before guessing.

## Always pair with documentation-writer

This skill covers only the **mechanics** of Zensical Markdown: which element to
use and how to write its syntax. It does not cover **writing quality** — clear
structure, user-focused framing, tone, and avoiding the AI writing patterns that
erode reader trust. That lives in the `documentation-writer` skill.

Whenever this skill is active, invoke the `documentation-writer` skill as well
and follow it for the prose. The two compose: `documentation-writer` decides
what to say and how to say it well; this skill decides how to render it richly.
(The reverse is not required — editing a plain README needs `documentation-writer`
alone, with no Zensical.)

## The authoring mandate

Great docs are not walls of prose. When you write or edit a Zensical page, do
not default to plain paragraphs and fenced code. **Actively look for places
where a rich element communicates better, and use it,** even when the user only
asked you to "write the docs." Prefer showing structure over describing it.

Reach for the right element by intent:

| When the content is... | Use | Why |
| ---------------------- | --- | --- |
| A warning, caveat, tip, or aside | **Admonition** (`!!! warning`, `!!! tip`) | Sets it apart without derailing the main flow |
| A workflow, decision path, or process | **Mermaid flowchart** | A diagram beats a numbered paragraph |
| Interactions between actors/services over time | **Mermaid sequence diagram** | Shows order and messages at a glance |
| A state machine, object model, or data model | **Mermaid state / class / ER diagram** | Structure is the point; draw it |
| The same task across languages / OSes / tools | **Content tabs** (`=== "macOS"`) | Collapses parallel prose into one switchable block |
| A tricky line or token inside a code sample | **Code annotation** (`# (1)!`) | Explains the exact spot without cluttering the code |
| A config file or command worth copying | **Code block** with `title=` and copy button | Names the file and makes it one-click copyable |
| An index/landing page summarizing sections | **Card grid** | Scannable overview with icons and links |
| Acronyms readers may not know | **Abbreviations / glossary** | Auto-tooltips every occurrence site-wide |
| Supplemental detail that would interrupt | **Footnote** | Keeps the main line clean |
| Optional deep-dive content | **Collapsible admonition** (`??? note`) | Present but out of the way until wanted |

Rules of thumb:

- If you're about to write "first... then... if X... otherwise...", it's
  probably a **flowchart** or **content tabs**.
- If you're about to add a caveat mid-paragraph, pull it into an **admonition**.
- If a code sample needs three sentences of explanation underneath, some of that
  is probably **code annotations** instead.
- Don't overdo it. One well-placed diagram is worth more than five decorative
  admonitions. Use richness where it earns its place.

## Quick start

```sh
zensical new mydocs   # scaffold docs/, zensical.toml, a GitHub Pages workflow
cd mydocs
zensical serve        # live-reload preview at http://localhost:8000
zensical build        # build the static site into site/
```

`zensical new` enables a default set of Markdown extensions that already unlocks
almost every feature below, so on a fresh project you can use them immediately.
When you add a page, wire it into navigation (auto from the folder tree, or
explicit `nav` in `zensical.toml`).

Full CLI options, project layout, and every config setting are in
`references/configuration.md`.

## Feature syntax at a glance

Enough to write good pages now. For the complete syntax of every feature (all
admonition types, all Mermaid diagram types, per-block code options, grids,
tables, math, images, and more), read `references/authoring.md`.

> **Four-space rule:** content nested inside an admonition, a tab, a multi-line
> list item, or a footnote must be indented **four spaces**. This is the number
> one cause of broken rendering.

### Admonitions

```markdown
!!! warning "Data loss"

    Running this drops the table. Back up first.

??? note "Optional background"

    Collapsed until the reader expands it.
```

Types: `note`, `abstract`, `info`, `tip`, `success`, `question`, `warning`,
`failure`, `danger`, `bug`, `example`, `quote`.

### Code blocks with title, line highlight, and annotations

````markdown
``` toml title="zensical.toml" hl_lines="2"
[project]
site_name = "My Project"   # (1)!
```

1.  This shows in the page header and the HTML `<title>`.
````

The `# (1)!` marker attaches the numbered note below to that exact line, and the
`!` strips the comment characters. Annotations can hold any Markdown.

### Content tabs

````markdown
=== "macOS"

    ``` sh
    brew install zensical
    ```

=== "Linux"

    ``` sh
    pip install zensical
    ```
````

### Mermaid diagrams

````markdown
``` mermaid
graph LR
  A[Write Markdown] --> B{zensical serve};
  B -->|looks good| C[zensical build];
  B -->|needs work| A;
```
````

Officially themed types: flowchart (`graph`), `sequenceDiagram`,
`stateDiagram-v2`, `classDiagram`, `erDiagram`. Avoid pie/gantt/journey diagrams
(unsupported, poor on mobile).

### Card grid (great for index pages)

```html
<div class="grid cards" markdown>

-   :material-clock-fast:{ .lg .middle } __Set up in 5 minutes__

    ---

    Install and preview your docs in minutes.

    [:octicons-arrow-right-24: Getting started](getting-started.md)

</div>
```

### Icons, emojis, and inline formatting

```markdown
:material-check: done   :fontawesome-brands-github: repo   :smile:

==highlight==   ^^insert^^   ~~strike~~   H~2~O   A^T^A   ++ctrl+c++
```

### Tables, lists, footnotes, tooltips

```markdown
| Method | Description         |
| ------ | ------------------- |
| `GET`  | :material-check: OK |

- [x] Done task
- [ ] Pending task

Referenced claim.[^1]

[^1]: The supporting footnote.

The W3C maintains the spec.

*[W3C]: World Wide Web Consortium
```

## Enabling features

If a feature renders as literal text, its Markdown extension is not enabled. The
`zensical new` defaults cover admonitions, code highlighting/annotation, content
tabs, Mermaid, grids, icons, formatting, lists, footnotes, and abbreviations.

A few features need an extension added to `zensical.toml`, and some behaviors are
opt-in **theme features** (`content.code.copy`, `content.code.annotate`,
`content.tabs.link`, `content.tooltips`, `content.footnote.tooltips`, the
`navigation.*` flags). The full default extensions block, the feature-to-extension
map, and theme flags are in `references/configuration.md`.

## Reference files

- **`references/authoring.md`** — complete, verbatim Markdown syntax for every
  authoring feature. Read this whenever writing or reviewing page content.
- **`references/configuration.md`** — CLI commands and options, `zensical.toml`
  settings, theme variant, colors/palette, navigation, theme feature flags, the
  full default extensions block, and extra CSS/JS. Read this whenever setting up
  or configuring a project.
