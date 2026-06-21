---
name: squash
description: Use when the user invokes /squash to collapse a finished feature branch or worktree into a single commit on main. Commits any outstanding work, squash-merges the whole branch into one conventional commit on the local main/master branch, then deletes the branch and removes its worktree. User-invoked only; this is an irreversible, destructive workflow.
disable-model-invocation: true
---

# Squash

Collapse a completed feature branch (or its worktree) into a single commit on
the local `main`/`master` branch, then clean up. This is the end-of-feature
"land it" workflow: one tidy commit on the trunk, no leftover branch.

This skill is **destructive and irreversible** once the deletions run. Force
through nothing — synthesize the message, verify the commit landed, then clean up.

## Non-negotiable guardrails

- **Never push.** The squash lands on the _local_ trunk only. Stop after
  cleanup and let the user push when they're ready.
- **The final commit message is for an end user, not a maintainer.** It
  describes the branch as one shipped feature and why the project's users
  benefit — not a changelog of every internal change. Synthesize it, then
  commit it directly (no approval prompt) and report the message used.
- **Verify before you delete.** Confirm the squash commit exists and holds the
  work _before_ removing any branch or worktree. Deletions are the last steps.
- **Conventional commits throughout.** Every commit this skill makes — the
  prep commits _and_ the final squash commit — must be a valid conventional
  commit (full rule in the shared prep reference below). The
  `enforce_commit_message` hook will reject anything else.

## Why this works with branch protection

This repo's `enforce_branch_protection` hook blocks commits directly on
`main`/`master` — **except** when a squash merge is in progress (it detects
`SQUASH_MSG` in the git dir, or a `git merge --squash ... && git commit` chain).
That carve-out exists for exactly this workflow. So the final commit _must_ go
through `git merge --squash` followed by `git commit`. Do not try to commit on
the trunk any other way; it will be blocked.

## Workflow

```dot
digraph squash {
  rankdir=TB; node [shape=box];
  detect   [label="Step 0: detect feature branch, trunk name,\nworktree or single checkout"];
  refuse   [label="On trunk already / nothing to squash?\nStop and explain" shape=diamond];
  prep     [label="Steps A-D: shared prep\n(commit, rebase on trunk, green, docs)"];
  goto     [label="Step 4: move to the trunk checkout,\ncheckout main, ensure clean"];
  squash   [label="git merge --squash <branch>"];
  conflict [label="Conflicts?" shape=diamond];
  resolve  [label="Stop. Report conflict, let user resolve"];
  msg      [label="Synthesize ONE user-facing\nconventional commit message"];
  commit2  [label="git commit  (allowed: squash in progress)"];
  verify   [label="Verify commit landed + holds the work"];
  cleanup  [label="Step 5: remove worktree (if any),\nforce-delete branch"];
  done     [label="Report result. Do NOT push." shape=doublecircle];

  detect -> refuse;
  refuse -> done [label="yes"];
  refuse -> prep [label="no"];
  prep -> goto -> squash -> conflict;
  conflict -> resolve [label="yes"];
  conflict -> msg [label="no"];
  msg -> commit2;
  commit2 -> verify -> cleanup -> done;
}
```

### Step 0 — Detect the situation

Establish four facts before touching anything:

```bash
git branch --show-current                 # the feature branch to squash
git rev-parse --git-dir                    # differs from below inside a worktree
git rev-parse --git-common-dir             # points at the real .git
git worktree list                          # shows every checkout + its branch
```

- **Trunk name**: prefer `main`; use `master` if that's what exists
  (`git rev-parse --verify main` / `master`).
- **Worktree vs single checkout**: if `--git-dir` and `--git-common-dir` resolve
  to different paths, you are in a _linked worktree_; the trunk lives in a
  separate checkout (find it in `git worktree list` — it's the one on
  `main`/`master`). Otherwise it's a single checkout and you'll switch it to the
  trunk yourself.

**Refuse early** if either:

- the current branch is already `main`/`master` (nothing to land), or
- the branch has no commits beyond the trunk **and** the working tree is clean
  (truly nothing to squash).

A branch that is level with the trunk but has _uncommitted_ changes is **not** a
refusal: the shared prep's first step commits that work onto the branch, leaving
exactly one commit to squash. Run `git status --porcelain` before refusing on
the second condition — if it prints anything, there is work to squash, so
proceed.

### Steps A–D — Prepare the branch (shared)

**Read `../shared/finishing-prep.md`** (relative to this skill's base directory)
and perform every step in it before continuing. Every commit it makes goes onto
the _feature branch_, never the trunk. Return here once it's done.

### Step 4 — Squash onto the trunk

Get onto the trunk checkout, confirm it's clean, then squash-merge the branch.

- **Single checkout**: `git checkout main` in the current repo.
- **Worktree**: `cd` into the trunk's checkout (from `git worktree list`); it's
  already on `main`. Confirm with `git status` that the trunk tree is clean
  before merging — a dirty trunk means stop and ask the user.

The shared prep (Step B) rebased the feature onto `origin/<trunk>`, so the local
trunk should match the remote before the squash — otherwise a stale local trunk
makes the merge drag in commits it was missing. On a remote-backed repo, run a
fast-forward first (skip on a local-only repo):

```bash
git merge --ff-only origin/<trunk>    # bring the checked-out local trunk current
```

Run it unconditionally on a remote-backed repo — it is safe in every case:

- **Local trunk current or _ahead_** (e.g. it holds prior unpushed squashes —
  the normal state for this never-push workflow): prints "Already up to date" and
  changes nothing. _Ahead is not divergence; do not skip the squash over it._
- **Local trunk behind**: fast-forwards it to the remote.
- **Truly diverged** (local has commits the remote lacks _and_ the remote has
  commits the local lacks): the command fails. **Stop and report** rather than
  forcing it.

```bash
git merge --squash <feature-branch>
```

This stages every change from the branch as _uncommitted_ work and writes
`SQUASH_MSG`. **If it reports conflicts, stop** — report which files conflict and
let the user resolve; do not guess at resolutions or abort their work.

Now write the final commit message. Read the branch's contribution for context,
but the message is **not** a changelog of it:

```bash
git log --oneline main..<feature-branch>   # context: the commits being collapsed
git diff --staged --stat                    # context: the net change landing on trunk
```

Describe the branch as **one feature, framed for an end user of the project** —
what they can now do and why it benefits them — not an inventory of every
internal change. The reader is someone scanning the trunk's history or a release
changelog, so reference the public-facing capability, not internal class names,
refactors, or intermediate commits. A branch with fifteen commits across five
files should still land as a single, coherent "here's what shipped and why"
message. Drop the incidental churn (test tweaks, lint fixes, renames) unless it
_is_ the user-facing point.

Draft one conventional commit (subject + body explaining the _why_ for the
user) and commit it directly — **do not pause for approval**. Report the
message you used as part of the final summary:

```bash
git commit -m "<type>(<scope>): <subject>" -m "<body>"
```

The branch-protection hook permits this commit because the squash merge is in
progress. Validate it landed before going further:

```bash
git log -1 --stat        # confirm the squash commit exists and holds the work
```

### Step 5 — Clean up

Only after the commit is verified. Squash merges leave **no merge ancestry**, so
git does not consider the branch merged — `git branch -d` will fail with "not
fully merged". Use `-D` (force). This is safe and _not_ blocked by the hook,
which only protects `main`/`master` from force-deletion.

Order matters: a branch checked out in a worktree can't be deleted, so remove
the worktree first.

```bash
# Worktree case only — frees the branch. Never rm -rf the directory by hand;
# let git remove it so its metadata is cleaned up too.
git worktree remove <worktree-path>

# Both cases — force-delete because the squash left no merge ancestry.
git branch -D <feature-branch>
```

If `git worktree remove` complains about untracked or dirty files, **stop and
report** rather than forcing — forcing would silently discard those files.

### Finish

Summarize what happened: the single squash commit (hash + subject) now on the
local trunk, the branch deleted, the worktree removed. Remind the user the trunk
is **not pushed** — that's theirs to do.

## Common failure modes

| Symptom                             | Cause                                         | Do this                                                                        |
| ----------------------------------- | --------------------------------------------- | ------------------------------------------------------------------------------ |
| Commit on trunk blocked             | Committed without an in-progress squash merge | Use `git merge --squash` then `git commit`; never commit on the trunk directly |
| `branch -d` says "not fully merged" | Squash merge records no merge ancestry        | Use `git branch -D` (expected, not an error)                                   |
| `worktree remove` refuses           | Untracked/dirty files in the worktree         | Stop, show the user; don't force-discard their files                           |
| Merge conflict on squash            | Trunk diverged from the branch's base         | Stop; let the user resolve, then resume at the commit step                     |
| Commit rejected by hook             | Message isn't a valid conventional commit     | Fix the type/subject; `chore` is not an allowed type here                      |
