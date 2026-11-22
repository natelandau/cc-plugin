---
name: zensical
description: "Use when authoring, building, configuring, or reviewing documentation with the Zensical static-site engine. Trigger on any zensical.toml or mkdocs.yml work, running zensical new/build/serve, writing docs/ Markdown pages, or requests to make documentation richer with Mermaid diagrams, admonitions/call-outs, code annotations, content tabs, grids, or icons. Also use whenever writing Markdown that will be published with Zensical, even if the user does not say 'Zensical' by name."
---

# Zensical documentation

Zensical (from the makers of Material for MkDocs) builds a site from a `docs/`
folder of Markdown plus `zensical.toml`. It evolves quickly: if a detail here
looks stale or a build errors on a setting, check <https://zensical.org/docs>
before guessing.

## Pair with technical-writer

This skill covers mechanics: which element to use and its syntax. Writing quality
(structure, framing, tone, avoiding AI writing patterns) lives in the
`natelandau-toolkit:technical-writer` skill. Whenever this skill is active, invoke
`natelandau-toolkit:technical-writer` too and follow it for the prose.

## Authoring mandate

When writing or editing a Zensical page, do not default to plain paragraphs and
fenced code. Look for places where a rich element communicates better and use it,
even when the user only asked to "write the docs". Show structure rather than
describe it.

Pick the element by intent:

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
| Acronyms readers may not know | **Abbreviations / glossary** | Auto-tooltips every occurrence on the page, or site-wide via a snippets glossary |
| Content that differs per product, edition, or deployment | **Directives** (`@if`, `@var`, `@use`) | One source builds several site variants (early access, needs an extension) |
| Supplemental detail that interrupts the flow | **Footnote** | Keeps the main line clean |
| Optional deep-dive content | **Collapsible admonition** (`??? note`) | Present but out of the way until wanted |

Rules of thumb:

- About to write "first... then... if X... otherwise...": use a **flowchart** or
  **content tabs**.
- Caveat mid-paragraph: pull it into an **admonition**.
- Code sample needing three sentences of explanation: move some into **code
  annotations**.
- Do not overdo it. One well-placed diagram beats five decorative admonitions.

## Quick start

Install: `uv add --dev zensical` (then prefix commands with `uv run`), or
`pip install zensical` in a virtual environment.

```sh
zensical new mydocs   # scaffold docs/, zensical.toml, a GitHub Pages workflow
cd mydocs
zensical serve        # live-reload preview at http://localhost:8000
zensical build        # build the static site into site/
```

`zensical new` enables default Markdown extensions covering almost every feature
below. Wire each added page into navigation (automatic from the folder tree, or
explicit `nav` in `zensical.toml`).

Page rules:

- Start every page with one `# H1`. With an explicit `nav` and no H1, Zensical
  titles the page from its filename.
- Link to other pages by relative path to the `.md` source
  (`[Setup](../setup/basics.md)`), never to generated `.html` or absolute URLs.
  Link and anchor validation is on by default and reports broken targets.
- Never put both `README.md` and `index.md` in one folder; the result is
  undefined.

CLI options, project layout, every config setting: `references/configuration.md`.

## Feature syntax at a glance

Complete syntax for every feature (all admonition and Mermaid types, per-block
code options, grids, tables, math, images): `references/authoring.md`.

Four-space rule: content nested inside an admonition, tab, multi-line list item,
or footnote must be indented four spaces. Most common cause of broken rendering.

### Admonitions

```markdown
!!! warning "Data loss"

    Running this drops the table. Back up first.

??? note "Optional background"

    Collapsed until the reader expands it.
```

Types: `note`, `abstract`, `info`, `tip`, `success`, `question`, `warning`,
`failure`, `danger`, `bug`, `example`, `quote`.

GitHub-style callouts (`> [!NOTE]`) work once `pymdownx.quotes` is enabled with
`callouts = true`. Prefer them when the Markdown must also render on GitHub.

### Code blocks with title, line highlight, and annotations

````markdown
``` toml title="zensical.toml" hl_lines="2"
[project]
site_name = "My Project"   # (1)!
```

1.  This shows in the page header and the HTML `<title>`.
````

`# (1)!` attaches numbered note 1 to that line; `!` strips the comment
characters. Annotations can hold any Markdown.

### Content tabs

````markdown
=== "uv"

    ``` sh
    uv add --dev zensical
    ```

=== "pip"

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
`stateDiagram-v2`, `classDiagram`, `erDiagram`. Other Mermaid types (pie, gantt,
journey) render unthemed and read poorly on mobile; prefer the themed ones.

### Card grid (index pages)

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

Icon shortcodes use the set prefix plus the icon name: `:lucide-check:`,
`:material-check:`, `:fontawesome-solid-check:`, `:octicons-check-16:`,
`:simple-github:`. Front matter and config use slashes instead:
`lucide/check`.

## Enabling features

A feature rendering as literal text means its Markdown extension is not enabled.
`zensical new` defaults cover admonitions, code highlighting/annotation, content
tabs, Mermaid, grids, icons, formatting, lists, footnotes, and abbreviations.

Some features need an extension added to `zensical.toml`; some behaviors are
opt-in theme features (`content.code.copy`, `content.code.annotate`,
`content.tabs.link`, `content.tooltips`, `content.footnote.tooltips`, the
`navigation.*` flags). Default extensions block, feature-to-extension map, and
theme flags: `references/configuration.md`.

## Reference files

- `references/authoring.md`: read when writing or reviewing page content.
  Verbatim Markdown syntax for every authoring feature, including directives.
- `references/configuration.md`: read when setting up or configuring a project.
  Install/upgrade, CLI, `zensical.toml` settings, file patterns, validation,
  theme variant, palette, navigation, theme feature flags, default extensions
  block, extra CSS/JS.
- `references/site-features.md`: read when adding one of these. Plugins and
  support status, search, tags, blog, redirects, offline, repository links,
  analytics and consent, language, GitHub/GitLab Pages publishing, template
  overrides, versioning with mike.
