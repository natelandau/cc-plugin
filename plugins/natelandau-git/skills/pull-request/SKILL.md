---
name: pull-request
description: Use when the user asks to open, create, make, or raise a pull request, or uses the shorthand "pr" in any form ("pr", "pr this", "open a pr", "make a PR"), including requests to push the branch and open a PR or to send the branch for review without saying "PR" (for example "get this reviewed" or "put this up for review"). Use it whenever a pull request is wanted, rather than running git push and gh pr create by hand. Commits any outstanding work, runs the project's linters and tests, pushes the feature branch, and opens a PR against the repo's default branch. The title and the opening of the description become the future squash commit, so they follow the user's commit conventions; detail for reviewers follows in sections such as Changes. Do not use for merging, squashing, or fast-forwarding a branch into main locally; those are different workflows.
---

# Pull request

Get the current feature branch committed and green, push it, and open a PR whose title
and lead block are the future squash commit.

## Guardrails

- Push the feature branch only; the PR request authorizes that push. Never push the
  trunk, never merge.
- Title and lead block land in `git log` byte for byte, so write them to the user's
  commit conventions. If rejected, fix them to the rules the block message lists.
- Every claim in the description is true of this branch and visible in the diff. No
  future work, open questions, or speculation; cut any that creeps in.
- A repo PR template replaces the default shape.
- Open ready for review; draft only when the user asks.

## Step 0: Detect the situation

```bash
git branch --show-current                                      # the branch to PR
git remote get-url origin                                      # the remote host
git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null  # origin/main, the base
```

- The default branch (strip `origin/`) is the PR base. If the ref is missing, run
  `git remote set-head origin --auto` and read again.
- On the default branch: stop; a PR opens from a feature branch. No remote: stop and
  say so.
- Pick the forge CLI for the host and use it for every PR operation:
  - github.com or GitHub Enterprise: `gh`
  - Gitea or Forgejo: `tea`
  - gitlab.com or self-hosted GitLab: `glab`
  - Unidentifiable self-hosted host: the CLI whose logins include it (`tea login list`,
    `glab auth status`, `gh auth status`)
- Matching CLI missing or not authenticated for the host: stop and ask the user to
  install it or log in (`gh auth login`, `tea login add`, `glab auth login`). Never fall
  back to another forge's CLI.
- Run "Existing PR for branch". If the PR already merged, stop before prep rebases
  anything: the work landed. Say so and offer to clean up the local branch and worktree
  and pull the trunk instead.
- Check for unpushed local-trunk commits riding on the branch. Do it before prep,
  because the rebase rewrites them and hides their origin. Skip when no local
  `<default-branch>` exists.

  ```bash
  git fetch origin <default-branch>
  git log --oneline origin/<default-branch>..$(git merge-base <default-branch> HEAD)
  ```

  Empty (the common case): move on. Otherwise the branch was cut from a local trunk
  ahead of the remote, and the PR would carry those commits as this work. Stop, show
  them, and ask the user to push the trunk first or confirm they belong in this PR.

### Commands per forge

`<base>` = default branch, `<branch>` = feature branch, `<body-file>` = temp file
holding the description.

| Operation              | GitHub (`gh`)                                                                          | Gitea / Forgejo (`tea`)                                                                            | GitLab (`glab`)                                                                                                            |
| ---------------------- | -------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| Create PR (ready)      | `gh pr create --base <base> --head <branch> --title "<title>" --body-file <body-file>` | `tea pr create --base <base> --head <branch> --title "<title>" --description "$(cat <body-file>)"` | `glab mr create --target-branch <base> --source-branch <branch> --title "<title>" --description "$(cat <body-file>)" --yes` |
| Open as draft (opt-in) | add `--draft`                                                                          | append ` [WIP]` to the title (tea has no draft flag)                                               | add `--draft`                                                                                                              |

`tea` and `glab` have no `--body-file`; pass `--description "$(cat <body-file>)"`.
`glab mr create` is interactive unless given `--yes`. Either CLI opening an editor or
hanging means one of these was missed.

Existing PR for branch (prints the PR with its state, open, merged, or closed, or
reports none):

- `gh`: `gh pr view <branch> --json url,state -q '.url + " (" + .state + ")"'`
- `tea`: `tea pulls list` can't filter by branch, so use the API (tea fills `{owner}`
  and `{repo}`). Match `.head.label`; Gitea rewrites `.head.ref` once the head branch is
  deleted:
  `tea api 'repos/{owner}/{repo}/pulls?state=all&sort=recentupdate&limit=50' | jq 'first(.[] | select(.head.label == "<branch>") | {html_url, state, merged})'`
- `glab`: `glab mr list` shows open MRs only, so run
  `glab mr list --source-branch <branch>` and
  `glab mr list --merged --source-branch <branch>`.

## Steps A to D: Prepare the branch

Read `../shared/finishing-prep.md` (relative to this skill's base directory) and do
every step, with `<rebase-onto>` = `origin/<default-branch>` (the PR merges into the
remote trunk). Return here when done.

## Step 4: Regroup a sprawled history

A few coherent commits review better than a trail of small or fixup commits.

```bash
orig=$(git rev-parse HEAD)   # pre-rewrite tip, for the byte-identical check
```

Read `../shared/regroup-history.md` (relative to this skill's base directory) and do
every step, with `<base>` = the default branch (the trunk from Step B) and
`<original-tip>` = `$orig`. If its closing gate is red, the tree is unchanged: report
the failures and stop. Don't open the PR and don't amend the group commits.

## Step 5: Push the branch

Run "Existing PR for branch". If a PR is already open, show its URL, offer to update
it, and stop. Otherwise:

```bash
git push -u origin HEAD
```

Rejected as non-fast-forward: the branch was pushed before the Step B rebase. That
needs a force push, which `enforce_branch_protection` blocks. Never force it; ask the
user to run `! git push --force-with-lease`, then continue.

## Step 6: Write the title and description

Read the whole branch; the diff is the ground truth:

```bash
git log --oneline <default-branch>..HEAD
git diff <default-branch>...HEAD
```

Look for a PR template; use the first path that exists:

```bash
# directory of named templates (GitHub/Gitea/Forgejo, then GitLab)
ls .github/PULL_REQUEST_TEMPLATE/ .gitea/PULL_REQUEST_TEMPLATE/ \
   .forgejo/PULL_REQUEST_TEMPLATE/ .gitlab/merge_request_templates/ 2>/dev/null
# single-file templates across forges
ls .github/PULL_REQUEST_TEMPLATE.md .github/pull_request_template.md \
   .gitea/PULL_REQUEST_TEMPLATE.md .gitea/pull_request_template.md \
   .forgejo/PULL_REQUEST_TEMPLATE.md \
   docs/pull_request_template.md PULL_REQUEST_TEMPLATE.md 2>/dev/null
```

- Template directory: use `default.md` if present, else ask which one.
- Single file: it is the body skeleton. Keep every heading in order, fill each truthfully,
  and mark one that does not apply `N/A`. Never invent content.
- No template: the shape below.

**Title and lead block.** The title is the squash subject. The lead block (everything
above the first markdown heading) is the squash body. Both follow the user's commit
conventions and are written from the whole diff at branch altitude, not from commit
subjects. Never paste a commit body or write a paragraph per commit.

**Breaking changes.** The squash keeps only title and lead block, so a branch commit's
breaking marker is lost unless the PR carries it. Scan for markers in the conventions'
form. For Conventional Commits:

```bash
git log <default-branch>..HEAD --format='%s' | grep -E '^[a-z]+(\([^)]*\))?!:'
git log <default-branch>..HEAD --format='%B' | grep -F 'BREAKING CHANGE'
```

No hit doesn't settle it; judge the diff. A changed exit code, removed or renamed flag,
new required argument, or changed default that alters output is a break whether or not
a commit said so. Mark every break in both title and lead block as the conventions
require. Never one marker without the other: add the missing one, or drop both when the
branch is not breaking.

**Review sections.** After the lead block, `##` sections carry detail the lead block
left out; they stay with the PR and are not squashed. Use the sections the user's
conventions name. If none, write `## Changes` listing the concrete changes, unless the
branch is a one-liner.

## Step 7: Create the PR

Write the body to a temp file (avoids shell quoting), then run "Create PR" for your
forge:

```bash
cat > /tmp/pr-body.md <<'EOF'
<lead block: the squash commit body>

## Changes

- <the concrete changes; review-only sections from here down, never squashed>
EOF

# GitHub example. Substitute the row for your detected CLI.
gh pr create --base <default-branch> --head "$(git branch --show-current)" \
  --title "<title>" --body-file /tmp/pr-body.md
```

Draft (`--draft` for `gh`/`glab`, `[WIP]` title prefix for `tea`) only when asked.
"a pull request already exists": show it and offer to update it.

Report the PR URL. State the feature branch was pushed and the trunk untouched; merging
is the user's or a reviewer's call. Add that once the PR merges, the local branch and
worktree can be cleaned up and the trunk pulled.
