---
name: cleanup-branch
description: Use when a pull request or merge request has been merged on the remote and the local branch, its worktree, or the stale local trunk still need cleaning up, even when the user never says "cleanup" (for example "the PR merged", "clean up after the merge", "delete merged branches", "prune merged worktrees", "sync main after merging"). Confirms the merge with the forge (GitHub, Gitea/Forgejo, GitLab), or by patch equivalence when there is no forge, so it works for squash, rebase, and merge-commit merges. Cleans up confirmed branches without asking and asks before deleting any branch with work the merge did not include. Removes the worktree, force-deletes the branch, and fast-forwards the local trunk. Handles the current branch, a named branch, or a sweep of every local branch. Never pushes, except an opt-in delete of the remote branch. Not for merging a branch locally, opening a PR, or regrouping a branch's commits.
---

# Cleanup branch

After a PR merged on the remote: remove the branch's worktree, delete the local branch,
fast-forward the local trunk.

A squash or rebase merge leaves no ancestry, so `git branch -d` refuses "not fully
merged" and the delete must be `-D`, which disables git's safety net. Two checks replace
it: proof the branch merged, and proof the local branch holds nothing the merge left
out.

## Guardrails

- Clean up without asking only when Step 2 confirms the merge and Step 3 passes. An
  upstream marked `[gone]` is not proof; it only means the remote branch was deleted.
  With nothing else confirming, ask in Step 4 as "upstream gone, unconfirmed".
- Delete an unconfirmed branch, or one holding commits the merge lacks, only when the
  user says yes to that branch in Step 4.
- Never force: no `git worktree remove --force`, stash, `reset`, or `pull` that can
  create a merge commit. A dirty or locked worktree is always skipped, never offered.
- The trunk moves only by fast-forward.
- Never push, except the Step 8 remote delete on a yes to that specific question.

## Step 0: Detect the situation

```bash
git symbolic-ref --short refs/remotes/origin/HEAD   # origin/main: the trunk
git worktree list --porcelain                       # every checkout, its branch, locked flag
git remote get-url origin                           # the forge host
git fetch --prune origin
```

- Strip `origin/` from the trunk. If the command fails, run
  `git remote set-head origin --auto` and read again.
- No `origin` remote: stop; nothing could have merged.
- From the worktree list, note the trunk's checkout, each branch's checkout, and the
  main checkout (first entry). Note whether the session cwd is inside a linked worktree
  (`git rev-parse --show-toplevel`).
- Pick the forge CLI and check auth:

| Host                                          | CLI    | Auth check         |
| --------------------------------------------- | ------ | ------------------ |
| github.com or GitHub Enterprise               | `gh`   | `gh auth status`   |
| Gitea or Forgejo                              | `tea`  | `tea login list`   |
| gitlab.com or self-hosted GitLab              | `glab` | `glab auth status` |
| Self-hosted host you cannot identify by name  | the CLI whose logins include the host | |
| Local path or `file://` URL (no network host) | none   | use the fallback   |

A missing or unauthenticated CLI is not a stop. Every branch goes to the stricter Step 2
fallback; say so in the report.

## Step 1: Pick the targets

- A named branch, when the user names one.
- The current branch, when it is not the trunk.
- Sweep, when the user asks for all merged branches, or the current branch is the trunk
  and none was named: every local branch except the trunk
  (`git for-each-ref --format='%(refname:short)' refs/heads`).

Never target the trunk.

## Step 2: Confirm the merge

Forge first. Git alone can't tell a squash merge from an abandoned branch.

- GitHub (fork PRs sharing the branch name are filtered, since `--head` can't name the
  fork owner). Number `.number`, URL `.url`, head SHA `.headRefOid`:

  ```bash
  gh pr list --head <branch> --state merged --json number,url,headRefOid,isCrossRepository \
    --jq '[.[] | select(.isCrossRepository | not)][0]'
  ```

- Gitea / Forgejo: `tea pulls list` lacks merged state, head filter, and head SHA, so
  use the API (tea fills `{owner}` and `{repo}`). Number `.number`, URL `.html_url`, head
  SHA `.head.sha`. Match `.head.label`; Gitea rewrites `.head.ref` to
  `refs/pull/<n>/head` once the head branch is deleted. A branch merged long ago can fall
  outside the 50 most recent: page with `&page=2` before calling it unmerged.

  ```bash
  tea api 'repos/{owner}/{repo}/pulls?state=closed&sort=recentclose&limit=50' \
    | jq '[.[] | select(.merged and .head.label == "<branch>"
                        and .head.repo_id == .base.repo_id)][0]'
  ```

- GitLab. Number `.iid`, URL `.web_url`, head SHA `.sha` (`-o` is `--order` in glab,
  not output):

  ```bash
  glab mr list --merged --source-branch <branch> --output json
  ```

Empty or `null`: no merged PR. Query merged PRs by head branch, never "the PR for this
branch": a reused name with a newer open PR would hide the merged one. Several matches:
use the most recent. A merged PR is the verdict; record its number, URL, and head SHA as
`<merged-head>`.

No usable CLI, or no merged PR (for example, squash-merged by hand): fall back to git.

```bash
git merge-base --is-ancestor <branch> origin/<trunk>   # exit 0: merged with ancestry
```

If that fails, probe for a squash: a throwaway commit holding the branch's whole diff,
checked for an equivalent patch on the trunk.

```bash
mb=$(git merge-base origin/<trunk> <branch>)
probe=$(git commit-tree "<branch>^{tree}" -p "$mb" -m probe)
git cherry origin/<trunk> "$probe"    # "- <sha>": an equivalent patch is on the trunk
```

The probe is unreferenced and garbage-collected. `+` means no equivalent patch: the
branch is unmerged, only partly merged, or conflict resolution changed the patch. All
three are "not confirmed" (Step 4 asks).

If the probe prints `+` and `origin/<branch>` still exists, probe `origin/<branch>` the
same way. A `-` there means the pushed branch merged and the local one has commits on
top. Report "merged, N local commits not in it" and list them
(`git log --oneline origin/<branch>..<branch>`).

Tag each verdict with its evidence: `PR #<n>`, `ancestor of trunk`, or
`patch-equivalent on trunk`.

## Step 3: Safety gates

Tip gate on Step 2's confirmed branches; worktree gates on every target, so Step 4
never offers a branch that can't be removed cleanly.

**Tip gate (forge verdict only).** The local branch holds no commit the merged PR
lacked: the local tip equals `<merged-head>` or is its ancestor (commits added on the
remote, such as applied review suggestions, are fine). The ancestry check needs
`<merged-head>` locally:

```bash
git cat-file -e "<merged-head>^{commit}" 2>/dev/null \
  || git fetch origin <pr-ref>
git merge-base --is-ancestor <branch> <merged-head>
```

`<pr-ref>`: `refs/pull/<n>/head` on GitHub and Gitea/Forgejo;
`refs/merge-requests/<iid>/head` on GitLab, which deletes it 14 days after merge. If the
object still can't be fetched, require the tip to equal `<merged-head>` exactly. On a
fail, list the extra commits (`git log --oneline <merged-head>..<branch>`): never
pushed, or pushed after the merge. The branch is unconfirmed; Step 4 asks.

Fallback verdicts need no tip gate; ancestry and the probe cover every local commit.

**Skip** (change nothing, never offer in Step 4, report it) when:

- Dirty worktree: the checkout has any change, untracked included
  (`(cd <absolute-checkout-path> && git status --porcelain)`). Never stash or commit for
  the user; report the files.
- Locked worktree: `git worktree list --porcelain` shows `locked`. Unlocking is the
  user's call.

## Step 4: Ask about branches not confirmed merged

Branches passing Steps 2 and 3 need no confirmation. Ask only about targets with no
merge found or a failed tip gate; skip this step if none. Show them in one table and ask
once which to delete anyway:

```text
Branch                Evidence                    Worktree                       Would lose
feat/wip              no merged PR                .worktrees/feat-wip            4 commits not on main
feat/review-fixes     PR #40                      -                              2 commits not in the PR
old/spike             upstream gone, unconfirmed  -                              7 commits not on main
```

List each row's commits (`git log --oneline origin/<trunk>..<branch>`, or
`<merged-head>..<branch>` for a tip-gate fail). Default is keep. Delete only the ones the
user names or clearly approves; report the rest as skipped. The remote delete is a
separate Step 8 question, never part of this one.

Nothing passed and nothing approved: report the verdicts and stop.

## Step 5: Leave the worktree first

Removing the session's cwd breaks every later shell call. If the cwd is inside a
worktree about to be removed:

- Entered with `EnterWorktree`: call `ExitWorktree` with `action: "keep"` (Step 6
  removes it).
- Otherwise `cd` to the trunk's checkout in its own Bash call.

If shell calls start failing after cleanup, the cwd was removed: `cd` to the trunk
checkout.

## Step 6: Remove the worktree, delete the branch

Per passing or approved branch, from outside the worktree. Record the tip first
(`git rev-parse --short <branch>`) for the report; until gc, `git branch <branch> <sha>`
restores it.

```bash
git worktree remove <worktree-path>   # never rm -rf the directory by hand
git branch -D <branch>                # Steps 2-3 are the safety net that -d cannot be
```

Branch checked out in the main checkout (no linked worktree): `git switch <trunk>` there
first, then delete.

If `git worktree remove` refuses, something changed since Step 3. Stop for that branch
and report. Never force.

## Step 7: Fast-forward the trunk

- Trunk checked out: `cd` there, then `git pull --ff-only origin <trunk>`. Local changes
  don't block it; git refuses if the fast-forward would overwrite one. Report and stop.
- Trunk not checked out: `git fetch origin <trunk>:<trunk>` (refuses anything but a
  fast-forward).

On divergence (local trunk has commits the remote lacks), stop and report. Never
rebase, merge, or reset the trunk.

## Step 8: Offer to delete the remote branch

For each branch deleted in Step 6 whose `origin/<branch>` survived the Step 0 prune, ask
separately whether to run `git push origin --delete <branch>`; proceed only on a clear
yes. Never offer skipped branches. None left: skip without asking. Mention that the
forge's auto-delete-head-branches setting makes this step unnecessary.

## Step 9: Report

```text
Cleaned up:
  feat/s3-auth   PR #42   worktree .worktrees/feat-s3-auth removed   was 3f9c2ab
  fix/timeout    patch-equivalent on trunk                          was 81d0e4c
  old/spike      not merged, deleted on request                     was 5d2e9a1

Skipped:
  feat/docs          dirty worktree (?? notes.txt)
  feat/wip           not merged, kept
  feat/review-fixes  2 commits not in PR #40, kept

main: e31c384 -> 9a1b7f0 (fast-forward, 3 commits).
Remote branches: none left to delete.
Merge evidence: forge (gh).
Nothing pushed.
```

"Merge evidence" names the fallback when used ("git ancestry and patch equivalence; no
forge CLI for this remote"). "Remote branches" lists those deleted or kept in Step 8.
