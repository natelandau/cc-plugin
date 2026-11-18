# Zensical site features, plugins, and publishing

Optional features beyond page authoring and core config. Each section gives
the `zensical.toml` form; `mkdocs.yml` takes the same keys in YAML.

## Table of contents

- [Plugins](#plugins)
- [Search](#search)
- [Tags](#tags)
- [Blog](#blog)
- [Redirects](#redirects)
- [llms.txt and Copy as Markdown](#llmstxt-and-copy-as-markdown)
- [Offline builds](#offline-builds)
- [Repository links and edit buttons](#repository-links-and-edit-buttons)
- [Comments](#comments)
- [Analytics, feedback, and cookie consent](#analytics-feedback-and-cookie-consent)
- [Language](#language)
- [Template overrides](#template-overrides)
- [Publishing](#publishing)
- [Versioning with mike](#versioning-with-mike)

---

## Plugins

Zensical runs only its own native plugins; there is no third-party plugin API
yet (a module API is planned). Configure each as a table:

```toml
[project.plugins.tags]

[project.plugins.minify]
minify_html = true
```

- Config for an unsupported plugin is silently ignored.
- Settings a supported plugin lists as ignored are silently ignored.
- Any other unknown setting on a supported plugin is a config error.
- `material/blog`, `material/search`, and similar `material/` names are accepted
  as aliases.

**Supported:** api-autonav, audio, autoapi, autorefs, awesome-nav, blog,
callouts, exclude, gh-admonitions, glightbox, include-markdown, literate-nav,
llmstxt, macros, markdown-exec, markdownextradata, meta, meta-descriptions,
mike, minify, mkdocstrings, nav-weight, offline, optimize, privacy, redirects,
rss, social, search, section-index (built in; the entry is ignored),
table-reader, tags, video.

Extra installs: mkdocstrings needs `mkdocstrings-python`; markdown-exec needs
`markdown-exec[ansi]`; optimize needs `pngquant` on `PATH` for PNG images.

**Unsupported:** `gen-files` (run its scripts before the build instead) and
`open-in-new-tab` (add its JavaScript through `extra_javascript`).

**Planned:** git-authors, git-committers, git-revision-date-localized.

Before configuring a plugin in depth, check its entry at
<https://zensical.org/docs/compatibility/mkdocs/plugins/> for its settings and
any that are ignored.

---

## Search

Built in and on by default. Only `enabled` and `separator` take effect; `lang`,
`pipeline`, `fields`, `indexing`, `min_search_length`, and `prebuild_index` are
ignored. The search language follows `theme.language`, and the search UI is in
English only.

```toml
[project.plugins.search]
enabled = true

[project.theme]
features = ["search.highlight"]
```

Exclude a page with front matter `search: {exclude: true}`, or one heading or
block with `{ data-search-exclude }`:

```markdown
## Internal notes { data-search-exclude }
```

---

## Tags

```toml
[project.plugins.tags]

[project.theme.icon.tag]
default = "lucide/hash"
html = "fontawesome/brands/html5"

[project.extra.tags]
HTML5 = "html"          # maps a tag to an icon identifier above
```

Pages list tags in front matter:

```yaml
---
tags:
  - HTML5
  - JavaScript
---
```

Put `<!-- material/tags -->` on any page to render a tag index there. Hide tags
on one page with `hide: [tags]`. The legacy `tags_file`, `tags_extra_files`,
`tags_compare*`, and `export*` settings are ignored; use the marker,
`tags_sort_by`, and `listings_sort_by` instead. Custom Python sort or slug
callables are not supported.

---

## Blog

A native port of the Material for MkDocs blog, so the Material blog docs are
the reference for options and post metadata. Custom Python callables are not
supported.

```toml
[project.plugins.blog]
```

Layout: `docs/blog/index.md` plus posts anywhere under `docs/blog/posts/`.
Each post needs a `date` (or `date.created` and `date.updated`) and can set
`draft`, `categories`, `authors`, and `links`. Authors are defined in
`docs/blog/.authors.yml`. `<!-- more -->` marks the end of the excerpt.

With an explicit `nav`, list only the blog index, never the posts:

```toml
[project]
nav = ["index.md", { "Blog" = ["blog/index.md"] }]
```

---

## Redirects

No install needed. Sources are relative to `docs_dir`; destinations can be
pages, anchors, or HTTPS URLs. Fragments carry over, and an unmapped anchor
falls back to the page redirect. Anchor-to-anchor redirects are a Zensical
addition.

```toml
[project.plugins.redirects.redirect_maps]
"old.md" = "new.md"
"current.md#old-heading" = "current.md#new-heading"
"old.md#api" = "reference/api.md"
```

Add a redirect whenever you move or rename a published page.

---

## llms.txt and Copy as Markdown

The `llmstxt` plugin writes an `llms.txt` index and Markdown copies of chosen
pages. `sections` is required; page paths accept globs:

```toml
[project.plugins.llmstxt.sections]
"Getting started" = ["index.md", "get-started/*.md"]
```

Optional: `markdown_description`, `base_url` (defaults to `site_url`),
`full_output` (a relative path inside `site_dir`), `autoclean`. `preprocess` is
ignored. Add the `content.action.copy` theme feature to show a "Copy as
Markdown" button on those pages.

---

## Offline builds

```toml
[project.plugins.offline]

[project.extra]
polyfills = ["js/iframe-worker-shim.js"]   # filename must contain "iframe-worker"
```

An offline build forces `use_directory_urls = false`. Turn off instant
navigation, analytics, the repository integration, and comments, because
anything that uses `fetch` breaks from `file://`. TOML has no environment-variable
toggle; `mkdocs.yml` can use `!ENV`.

---

## Repository links and edit buttons

```toml
[project]
repo_url = "https://github.com/acme/project"
repo_name = "acme/project"
edit_uri = "edit/main/docs/"      # derived automatically for GitHub

[project.theme]
features = ["content.action.edit", "content.action.view"]

[project.theme.icon]
repo = "fontawesome/brands/git-alt"
edit = "material/pencil"
view = "material/eye"
```

---

## Comments

Giscus (GitHub Discussions) is the documented option. Override the empty
`overrides/partials/comments.html` partial with the Giscus snippet wrapped in
`{% if page.meta.comments %}`, then turn comments on per page with front matter
`comments: true`. See <https://zensical.org/docs/setup/comment-system/> for the
full partial, including the palette sync script.

---

## Analytics, feedback, and cookie consent

The analytics integration is being reworked upstream; check the live docs
before building on it.

```toml
[project.extra.analytics]
provider = "google"
property = "G-XXXXXXXXXX"

[project.extra.analytics.feedback]
title = "Was this page helpful?"

[[project.extra.analytics.feedback.ratings]]
icon = "material/emoticon-happy-outline"
name = "This page was helpful"
data = 1
note = "Thanks for your feedback!"

[[project.extra.analytics.feedback.ratings]]
icon = "material/emoticon-sad-outline"
name = "This page could be improved"
data = 0
note = "Thanks for your feedback!"

[project.extra.consent]
title = "Cookie consent"
description = "We use cookies to measure how the documentation is used."
actions = ["accept", "manage"]
```

- The feedback widget needs both `title` and `ratings`, and the Google provider
  unless you build a custom integration.
- Another service: `provider = "custom"` plus an
  `overrides/partials/integrations/analytics/custom.html` partial.
- Hide the widget on one page with `hide: [feedback]`.
- Let visitors change consent later by adding
  `<a href="#__consent">Change cookie settings</a>` to `copyright`.

---

## Language

```toml
[project.theme]
language = "en"
direction = "ltr"

[project.extra]
alternate = [
  { name = "English", link = "/en/", lang = "en" },
  { name = "Deutsch", link = "/de/", lang = "de" },
]
```

`alternate` adds a language selector that links to separately built sites.
For custom UI strings, set `language = "custom"` and add an
`overrides/partials/languages/custom.html` partial.

---

## Template overrides

Set `custom_dir = "overrides"` under `[project.theme]`, then:

- Override blocks in `overrides/main.html` with `{% extends "base.html" %}`.
- Replace partials at the same path under `overrides/partials/`.
- `overrides/404.html` replaces the error page.

Templates render with MiniJinja, which cannot call Python functions.

---

## Publishing

**GitHub Pages:** `zensical new` already creates `.github/workflows/docs.yml`.
Set the repository's Pages source to "GitHub Actions". The workflow:

```yaml
name: Documentation
on:
  push:
    branches:
      - master
      - main
permissions:
  contents: read
  pages: write
  id-token: write
jobs:
  deploy:
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    runs-on: ubuntu-latest
    steps:
      - uses: actions/configure-pages@v6
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v6
        with:
          python-version: 3.x
      - run: pip install zensical
      - run: zensical build --clean
      - uses: actions/upload-pages-artifact@v5
        with:
          path: site
      - uses: actions/deploy-pages@v5
        id: deployment
```

Do not add CI caching yet; upstream advises against it while caching changes.

**GitLab Pages** (`.gitlab-ci.yml`; untick "Use unique domain" in Pages
settings):

```yaml
pages:
  stage: deploy
  image: python:latest
  script:
    - pip install zensical
    - zensical build --clean
  pages:
    publish: site
  rules:
    - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'
```

Any static host works: upload `site/`. There is no `gh-deploy` command.

---

## Versioning with mike

A stopgap until native versioning lands. It needs a fork of mike:

```sh
pip install git+https://github.com/squidfunk/mike.git
```

```yaml
extra:
  version:
    provider: mike
```

Zensical ignores mike's `css_dir` and `javascript_dir`.
