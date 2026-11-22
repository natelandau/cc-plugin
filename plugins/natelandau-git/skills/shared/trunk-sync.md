# Landing on the local trunk: shared steps

The caller says which section to run and when. `<trunk>` and `<feature-branch>` come
from Detect.

## Detect

```bash
git branch --show-current       # the feature branch
git rev-parse --git-dir         # differs from the next line inside a worktree
git rev-parse --git-common-dir  # the real .git
git worktree list               # every checkout and its branch
```

- Trunk: `main`, or `master` if that is the one that exists (`git rev-parse --verify main`).
- Layout: if `--git-dir` and `--git-common-dir` differ, you are in a linked worktree;
  the trunk is the checkout on the trunk in `git worktree list`. No checkout on the
  trunk: stop and report. Otherwise it is a single checkout, switched to the trunk in
  Return to the trunk.

Stop and explain if the current branch is the trunk, or if the branch has no commits
beyond the trunk and `git status --porcelain` is empty. A branch level with the trunk
but with uncommitted changes is fine: prep commits it, leaving one commit to land.

## Sync the local trunk

The local trunk can be ahead (unpushed landings) or behind its remote. Bring it current
before prep rebases onto it, so conflicts surface during prep. Skip on a local-only
repo.

```bash
git fetch --all --prune
```

Fast-forward without rewinding a locally-ahead trunk:

- Single checkout (trunk not checked out; the tree can be dirty). Update the ref only
  when the remote is strictly ahead:

  ```bash
  ahead=$(git rev-list --count origin/<trunk>..<trunk>)    # local-only commits
  behind=$(git rev-list --count <trunk>..origin/<trunk>)   # remote-only commits
  if [ "$behind" -gt 0 ] && [ "$ahead" -gt 0 ]; then
      echo "DIVERGED: both sides have unique commits"      # stop and report, never force
  elif [ "$behind" -gt 0 ]; then
      git fetch . origin/<trunk>:<trunk>                   # remote strictly ahead: fast-forward
  fi
  # ahead-only or equal: nothing to do
  ```

- Worktree (trunk checked out elsewhere). Fast-forward in place:

  ```bash
  git -C <trunk-checkout> merge --ff-only origin/<trunk>   # diverged: fails, so stop
  ```

On divergence, stop and report. Never force the trunk to either side.

## Return to the trunk

Get onto the trunk checkout:

- Single checkout: `git checkout <trunk>`.
- Worktree: `cd` into the trunk's checkout. If `git status` shows a dirty tree, stop
  and ask the user.

Remote-backed repo: confirm the trunk is still current.

```bash
git merge --ff-only origin/<trunk>    # expected: "Already up to date"
```

Behind or diverged means the remote moved since the sync: stop, report, restart the
caller's workflow from its sync step.

Every repo, local-only included:

```bash
git merge-base --is-ancestor <trunk> <feature-branch>   # exit 0: still rebased on the trunk
```

Non-zero means the local trunk moved since prep's rebase (for example, another worktree
landed work). Landing would put a tree the gates never checked on the trunk and can
silently undo the newer trunk work. Stop, report, restart the caller's workflow
from its sync step.
