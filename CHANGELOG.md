## v0.14.1 (2026-06-27)

### Fix

- **build**: track recall plugin version with commitizen

## v0.14.0 (2026-06-27)

### Feat

- **recall**: backfill project memory from past session transcripts (#13)
- **recall**: hand off working context to the next session
- **recall**: add memory reviewer agents and backlog triage skill
- **recall**: capture fewer, higher-value project memories

### Refactor

- **hooks**: remove the stop-phrase guard Stop hook
- **recall**: drop architecture.md memory tier

## v0.13.0 (2026-06-27)

### Feat

- **recall**: add the natelandau-recall project-memory plugin (#12)
- **hooks**: exempt gitignored Bash writes on protected branches
- **hooks**: show each uv nudge once per session

### Fix

- **hooks**: close secret, branch-protection, and config bypasses (#10)

### Refactor

- **hooks**: make only stage dispatchers executable scripts
- **hooks**: simplify secret and system protection rule config
- **hooks**: consolidate shared logic into lib helpers (#9)
- **hooks**: one dispatcher per stage with per-stage plugin dirs (#8)

## v0.12.0 (2026-06-23)

### Feat

- **hooks**: catch deferred work before Claude ends a turn

## v0.11.0 (2026-06-22)

### Feat

- **skills**: add /fast-forward to land branches on the local trunk

### Fix

- **hooks**: block merge commits on protected branches

## v0.10.0 (2026-06-22)

### Feat

- **pr**: support any forge CLI (gh, tea, glab), not just gh
- **hooks**: let projects add their own rules to the safety hooks

## v0.9.0 (2026-06-21)

### Feat

- **skills**: add /cleanup-branch and run heavy steps via subagents
- **pr**: consolidate sprawling branches before opening a PR
- **hooks**: match rules against multiple tool inputs
- **pr**: use a repo's pull-request template when opening a PR

## v0.8.1 (2026-06-20)

### Fix

- **skills**: share branch-finishing prep between /pr and /squash
- **commands**: show plain-language confidence labels in review reports

### Refactor

- **squash**: land /squash without a commit-message approval pause

## v0.8.0 (2026-06-19)

### Feat

- **commands**: add /organize for project navigability review

## v0.7.0 (2026-06-19)

### Feat

- **commands**: add /refactor for safe refactoring in any language
- **skills**: add web accessibility (WCAG 2.2) skill
- **hooks**: protect linter and formatter configs from being weakened
- **hooks**: allow edits to gitignored files on protected branches
- **hooks**: route PreToolUse hooks through a configurable dispatcher (#7)

### Fix

- **hooks**: harden input handling against malformed payloads

## v0.6.1 (2026-06-19)

### Fix

- **skills**: add documentation review to pr and squash skills

## v0.6.0 (2026-06-16)

### Feat

- **skills**: add /pr command to open a pull request for a branch
- **skills**: add /squash command to land a branch as one commit

## v0.5.2 (2026-06-15)

### Fix

- **hooks**: fire stop-phrase guard on split messages and real dodges

## v0.5.1 (2026-06-14)

### Fix

- **skills**: allow model invocation

## v0.5.0 (2026-06-02)

### Feat

- **hooks**: enforce commit format on gh pr titles
- **skills**: add tufte visualization skill

## v0.4.1 (2026-05-12)

### Fix

- **skills**: update nclutils skill to v3.4.0
- **skills**: update nclutils skill

## v0.4.0 (2026-05-11)

### Feat

- **skill**: add nclutils skill
- **hooks**: add protect_system for destructive commands (#5)

### Refactor

- **hooks**: externalize rule data to sibling TOML files (#6)

## v0.3.1 (2026-05-10)

### Fix

- **skills**: remove skills that should be rules

## v0.3.0 (2026-05-10)

### Feat

- **skills**: remove beanie-odm
- **skills**: require manual invocation for niche skills

## v0.2.0 (2026-05-09)

### Feat

- **hooks**: enforce conventional commit format (#4)
- **hooks**: add protect_secrets, drop require_pr_checks
- distribute as marketplace (#2)
- add initial plugin scope

### Fix

- **tests**: isolate repos fixture from inherited GIT_* env vars
- **commands**: use argument-hint in create-prd frontmatter
