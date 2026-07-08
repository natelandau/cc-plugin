# Zensical configuration and CLI reference

Zensical is the static documentation engine from the creators of Material for
MkDocs. It builds a documentation site from a directory of Markdown files plus a
`zensical.toml` config. It natively reads legacy `mkdocs.yml` too, but new
projects should use `zensical.toml`.

## Table of contents

- [CLI commands](#cli-commands)
- [Project layout](#project-layout)
- [The `zensical.toml` config](#the-zensicaltoml-config)
- [Core settings](#core-settings)
- [Theme variant](#theme-variant)
- [Colors and palette](#colors-and-palette)
- [Navigation](#navigation)
- [Theme feature flags](#theme-feature-flags)
- [Markdown extensions](#markdown-extensions)
- [Extra CSS and JavaScript](#extra-css-and-javascript)
- [TOML vs YAML syntax](#toml-vs-yaml-syntax)

---

## CLI commands

General form: `zensical COMMAND [OPTIONS] [ARGS]...`. Get help with
`zensical --help` or `zensical <command> --help`.

| Command | Purpose |
| ------- | ------- |
| `zensical new [PATH]` | Scaffold a new project. Creates `PATH` if missing; uses cwd if omitted. Will not overwrite an existing `zensical.toml`. |
| `zensical build` | Build the static site into `site_dir` (default `site/`). |
| `zensical serve` | Start a local preview server with live reload (preview only, not for production). |

**`build` options:**

| Option | Short | Description |
| ------ | ----- | ----------- |
| `--config-file` | `-f` | Path to the config file to use. |
| `--clean` | `-c` | Clean the cache. |
| `--strict` | `-s` | Enable strict mode (fail on warnings). |
| `--help` | | Show help and exit. |

**`serve` options:**

| Option | Short | Description |
| ------ | ----- | ----------- |
| `--config-file` | `-f` | Path to the config file to use. |
| `--open` | `-o` | Open the preview in the default browser. |
| `--dev-addr <IP:PORT>` | `-a` | Bind address (default `localhost:8000`). |
| `--help` | | Show help and exit. |

Typical loop: `zensical new mydocs` → edit files under `docs/` → `zensical serve`
to preview → `zensical build` for the final site.

---

## Project layout

`zensical new` scaffolds:

```
.
├─ .github/workflows
│  └─ docs.yml          # GitHub Actions workflow to build + publish to GitHub Pages
├─ docs/
│  ├─ index.md          # landing page
│  └─ markdown.md        # starter page
└─ zensical.toml        # project configuration (commented starter)
```

`docs/` holds the Markdown sources (change with `docs_dir`). The `.github`
folder can be edited for your CI or removed if you deploy elsewhere.

---

## The `zensical.toml` config

Everything currently lives under the `[project]` scope:

```toml
[project]
site_name = "My Project"
site_url = "https://example.com"
```

If the file contains no `markdown_extensions` definitions, Zensical applies a
sensible default set (see below). Keep the defaults until you have a reason to
change them.

---

## Core settings

All under `[project]`.

| Setting | Required | Notes |
| ------- | -------- | ----- |
| `site_name` | yes | Site name in HTML head and page headers. |
| `site_url` | recommended | Canonical URL; set unless building for offline use. |
| `site_description` | optional | Default `<meta>` description when a page omits its own. |
| `site_author` | optional | Author in the HTML head. |
| `copyright` | optional | Footer notice; plain text or an HTML fragment, e.g. `"&copy; 2025 Jane Doe"`. |
| `docs_dir` | optional | Source dir, relative to config. Default `docs`. Cannot be `.` yet. |
| `site_dir` | optional | Output dir, relative to config. Default `site`. |
| `use_directory_urls` | optional | `true` (default) gives clean `/usage/` URLs; `false` gives `/usage.html`. Forced `false` for offline builds. |
| `dev_addr` | optional | Preview bind address. Default `localhost:8000`. |
| `watch` | optional | Extra paths to watch during preview, e.g. `["data.csv", "fragments"]`. A change triggers a full rebuild. |
| `extra` | optional | Arbitrary key-value pairs for templates (`[project.extra]`). |

Not yet supported from `mkdocs.yml`: `remote_branch`, `remote_name`,
`exclude_docs`, `draft_docs`, `not_in_nav`, `hooks`.

---

## Theme variant

Two variants: `modern` (default, fresh design) and `classic` (matches Material
for MkDocs exactly). Switch with:

```toml
[project.theme]
variant = "classic"
```

---

## Colors and palette

Two built-in color schemes: `default` (light) and `slate` (dark).

**Fixed scheme + primary/accent color:**

```toml
[project.theme.palette]
scheme = "default"

[project.theme]
palette.primary = "indigo"
palette.accent = "indigo"
```

Primary colors: `red`, `pink`, `purple`, `deep-purple`, `indigo`, `blue`,
`light-blue`, `cyan`, `teal`, `green`, `light-green`, `lime`, `yellow`, `amber`,
`orange`, `deep-orange`, `brown`, `grey`, `blue-grey`, `black`, `white`. Accent
colors are the same list minus the neutrals (up to `deep-orange`).

**Light/dark toggle** (define `palette` as a list of tables; each needs a
`toggle.icon` from a bundled icon set and a `toggle.name`):

```toml
[[project.theme.palette]]
scheme = "default"
toggle.icon = "lucide/sun"
toggle.name = "Switch to dark mode"

[[project.theme.palette]]
scheme = "slate"
toggle.icon = "lucide/moon"
toggle.name = "Switch to light mode"
```

Each palette entry can also carry its own `primary`/`accent`.

---

## Navigation

By default the sidebar is built from the folder structure. For explicit control,
set `nav` (paths relative to `docs_dir`):

```toml
[project]
nav = [
  "index.md",
  "about.md"
]
```

**Explicit titles** and **sections** (nested lists):

```toml
[project]
nav = [
  {"Home" = "index.md"},
  {"About" = [
     "about/index.md",
     "about/vision.md",
     "about/team.md"
  ]}
]
```

**External links**, any string that doesn't resolve to a page is treated as a
URL:

```toml
nav = [
  {"GitHub Repo" = "https://github.com/zensical/docs"}
]
```

---

## Theme feature flags

Opt-in behaviors, listed under `[project.theme]` as `features = [...]`. Combine
the ones you want:

```toml
[project.theme]
features = [
    "navigation.instant",
    "navigation.tabs",
    "navigation.sections",
    "navigation.top",
    "content.code.copy",
    "content.code.annotate",
    "content.tabs.link",
    "content.tooltips",
]
```

Common flags:

- **Content:** `content.code.copy`, `content.code.select`,
  `content.code.annotate`, `content.tabs.link`, `content.tooltips`,
  `content.footnote.tooltips`.
- **Navigation:** `navigation.instant`, `navigation.instant.prefetch`,
  `navigation.instant.progress`, `navigation.tabs`, `navigation.tabs.sticky`,
  `navigation.sections`, `navigation.expand`, `navigation.path`,
  `navigation.indexes`, `navigation.prune`, `navigation.top`,
  `navigation.tracking`.
- **Table of contents:** `toc.follow`, `toc.integrate`.

---

## Markdown extensions

The default set enabled by `zensical new` (enables nearly every authoring
feature). This is the recommended baseline; copy it verbatim to enable
admonitions, code annotations, content tabs, Mermaid diagrams, and more:

```toml
[project.markdown_extensions.abbr]
[project.markdown_extensions.admonition]
[project.markdown_extensions.attr_list]
[project.markdown_extensions.def_list]
[project.markdown_extensions.footnotes]
[project.markdown_extensions.md_in_html]
[project.markdown_extensions.toc]
permalink = true
[project.markdown_extensions.pymdownx.arithmatex]
generic = true
[project.markdown_extensions.pymdownx.betterem]
[project.markdown_extensions.pymdownx.caret]
[project.markdown_extensions.pymdownx.details]
[project.markdown_extensions.pymdownx.emoji]
emoji_generator = "zensical.extensions.emoji.to_svg"
emoji_index = "zensical.extensions.emoji.twemoji"
[project.markdown_extensions.pymdownx.highlight]
anchor_linenums = true
line_spans = "__span"
pygments_lang_class = true
[project.markdown_extensions.pymdownx.inlinehilite]
[project.markdown_extensions.pymdownx.keys]
[project.markdown_extensions.pymdownx.magiclink]
[project.markdown_extensions.pymdownx.mark]
[project.markdown_extensions.pymdownx.smartsymbols]
[project.markdown_extensions.pymdownx.superfences]
custom_fences = [
  { name = "mermaid", class = "mermaid", format = "pymdownx.superfences.fence_code_format" }
]
[project.markdown_extensions.pymdownx.tabbed]
alternate_style = true
combine_header_slug = true
[project.markdown_extensions.pymdownx.tasklist]
custom_checkbox = true
[project.markdown_extensions.pymdownx.tilde]
```

Some authoring features need an extension **not** in the default set. Add these
when you use the feature:

- **Content tabs:** already covered by `pymdownx.tabbed` above.
- **Snippets** (embed files, glossary auto-append): add
  `[project.markdown_extensions.pymdownx.snippets]`.
- **Image captions:** add
  `[project.markdown_extensions.pymdownx.blocks.caption]`.
- **Data tables:** add `[project.markdown_extensions.tables]` (usually on by
  default; add it to be sure).

To reset to the bare MkDocs default (`meta`, `toc`, `tables`, `fenced_code`
only), set `markdown_extensions = {}`.

Extensions map to features:

| Feature | Extension(s) |
| ------- | ------------ |
| Admonitions | `admonition`, `pymdownx.details` |
| Code highlighting + copy/annotate | `pymdownx.highlight`, `pymdownx.inlinehilite`, `pymdownx.superfences` |
| Embed external files | `pymdownx.snippets` |
| Content tabs | `pymdownx.tabbed` (`alternate_style = true`) |
| Mermaid diagrams | `pymdownx.superfences` mermaid custom fence |
| Grids / buttons / attributes | `attr_list`, `md_in_html` |
| Icons and emojis | `attr_list`, `pymdownx.emoji` |
| Highlight / sub / sup / keys | `pymdownx.caret`, `pymdownx.mark`, `pymdownx.tilde`, `pymdownx.keys` |
| Definition + task lists | `def_list`, `pymdownx.tasklist` |
| Footnotes | `footnotes` |
| Tooltips + abbreviations | `abbr`, `attr_list`, `pymdownx.snippets` |
| Image captions | `pymdownx.blocks.caption` |
| Math | `pymdownx.arithmatex` (`generic = true`) + MathJax/KaTeX JS |

Zensical-only extensions also exist: GLightbox (image lightbox), Macros,
mkdocstrings.

---

## Extra CSS and JavaScript

Add stylesheets and scripts, relative to `docs_dir` or absolute URLs:

```toml
[project]
extra_css = ["stylesheets/extra.css"]
extra_javascript = ["javascripts/custom.js"]
```

These power icon colors/animations, custom code syntax themes, Mermaid
customization, MathJax/KaTeX, and sortable tables.

**Mermaid customization** example (custom JS module):

```toml
[project]
extra_javascript = ["javascripts/mermaid.mjs"]
```

**Math (MathJax)** example:

```toml
[project]
extra_javascript = [
    "javascripts/mathjax.js",
    "https://unpkg.com/mathjax@3/es5/tex-mml-chtml.js"
]
[project.markdown_extensions.pymdownx.arithmatex]
generic = true
```

---

## TOML vs YAML syntax

Zensical documents both. TOML is recommended; `mkdocs.yml` is supported for
migration.

```toml
# zensical.toml
[project]
site_name = "My Project"
[project.markdown_extensions.pymdownx.tabbed]
alternate_style = true
```

```yaml
# mkdocs.yml
site_name: My Project
markdown_extensions:
  - pymdownx.tabbed:
      alternate_style: true
```

Note the YAML `!!python/name:` and `!!python/object/apply:` tags (e.g. for the
Mermaid fence format or emoji generators) become plain string values in TOML,
e.g. `format = "pymdownx.superfences.fence_code_format"`.
