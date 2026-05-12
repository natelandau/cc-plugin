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
