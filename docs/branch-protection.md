# Branch protection: what git actions are allowed, blocked, or prompted

The `branch-protection` hook (part of `natelandau-toolkit`) keeps work off your
trunk by accident. It runs before every `Bash`, `Edit`, `Write`, and
`NotebookEdit` tool call and decides one of three things: allow the action, hard
block it, or route it to the permission prompt for your approval.

This page lists the exact rules. The hook's behavior in code lives in
`plugins/natelandau-toolkit/hooks/pretooluse/enforce_branch_protection.py`; this
page is the human-readable companion.

## The one idea behind every rule: the target's branch decides

The hook judges an action by the branch of the thing it touches, not by the
directory your shell happens to sit in.

- An `Edit`/`Write` is judged by the branch of the file being edited.
- A file-modifying Bash command (`rm`, `>`, `cp`, ...) is judged by the branch
  of each file it writes.
- A `git commit`/`merge`/`pull` is judged by the branch of the repo it operates
  on, read from `git -C <path>` or a leading `cd <path> &&` when present.

So a write into a repo on `main` is caught even when you run it from a feature
worktree, and a write into a feature branch passes even when your shell is on
`main`. Protected branches are `main` and `master`.

## Git operations

The table covers git actions aimed at a protected branch. Actions on a feature
branch are unaffected by branch protection (destructive operations are the
exception; see below).

| Action | Decision | Why |
| --- | --- | --- |
| `git status`, `git log`, `git diff`, other read-only git | Allow | Reads never change history. |
| `git commit` on a protected branch | Block | A direct commit to trunk is almost always a "forgot to branch" mistake. |
| `git commit` from inside a linked worktree | Allow | Worktrees are the supported path for isolated work. |
| `git commit` finishing a squash merge (`git merge --squash X && git commit`) | Allow | The follow-up commit is expected; the merge staged the changes. |
| `git merge`, `git merge --no-ff`, `git pull` (a real merge commit) | Ask | A merge onto trunk is sometimes a deliberate, human-approved integration. You approve or reject. |
| `git merge --ff-only`, `git merge --squash`, `git merge --abort`, `git merge --quit` | Allow | These cannot write a merge commit to the branch. |
| `git pull --ff-only`, `git pull --rebase`, `git pull -r` | Allow | Fast-forward or rebase, no merge commit. |
| `git apply`, `git am`, `git stash pop`, `git stash apply` | Block | These rewrite tracked files in the working tree, the same as an edit on trunk. |
| `git apply --check`/`--stat`/`--numstat`/`--summary`, `git am --abort`/`--quit`/`--show-current-patch` | Allow | Inspection and recovery forms that apply nothing. |

The hook recognizes `git -C <path>` and `-c key=val` options before the
subcommand, so `git -C /path/to/repo commit` is judged against `/path/to/repo`,
not your shell's directory.

### Why a merge commit asks instead of blocks

A hard block fits operations that are destructive and never a legitimate
agent-initiated action, such as a force push. A merge commit is neither. It is
reversible, and merging a release branch into `main` is a real, intended
workflow for some teams. An "ask" keeps you in control: Claude cannot approve
its own prompt, so it still cannot land a merge on trunk without you, but you are
not locked out of a merge you actually want.

To land work on a protected branch without a merge commit, use a fast-forward
(`git merge --ff-only <branch>`) or a squash merge (`git merge --squash <branch>
&& git commit`).

## File modifications

On a protected branch, a Bash command that writes a tracked file is blocked.
The hook reads the write targets from the command and checks each one:

| Write form | Examples |
| --- | --- |
| Positional file arguments | `rm`, `rmdir`, `mv`, `cp`, `touch`, `mkdir`, `chmod`, `chown`, `ln`, `install` |
| Output redirects | `> file`, `>> file`, `2> file`, `2>> file` |
| In-place and download writers | `sed -i`, `perl -i`, `curl -o`/`-O`, `wget`, `tee` |
| Bulk and in-place writers without a positional target | `truncate`, `dd of=<path>` (except `of=/dev/null`), `find ... -delete`, `xargs rm` |

The command name is read past a leading launcher (`sudo`, `env`, `command`,
`nice`, `time`), an absolute path (`/bin/rm`), or a subshell/group opener
(`( rm ... )`), so these do not slip the rules. Metacharacters inside quotes are
treated as data, not syntax, so a quoted program like `awk 'c>=2'` or
`grep 'a>b'` is not mistaken for a redirect.

A write is allowed, even on a protected branch, when its target is harmless:

- The target resolves to a path that is not inside a repository on a protected
  branch. This covers scratch paths under `/tmp`, `/dev/null`, and anything
  outside a repo, because the branch lookup returns nothing for them.
- The target is gitignored (never part of tracked history).

A `..` segment, and any symlink, is resolved to its real destination before the
check. A path that resolves to a non-repo location is allowed; one that resolves
back into a repo on a protected branch is blocked, even a repo that happens to
live under `/tmp`.

`Edit`, `Write`, and `NotebookEdit` follow the same logic: blocked on a protected
branch unless the target file is gitignored.

## Destructive operations (every branch)

These rewrite or discard history and are blocked on every branch, not just
protected ones. There is no feature-branch exemption, because the damage does
not depend on which branch you are on.

| Operation | Reason |
| --- | --- |
| `git push --force`, `git push -f`, `git push --force-with-lease`, `git push origin +ref` | Rewrites remote history; can destroy others' work. |
| `git reset --hard` | Discards uncommitted changes irrecoverably. |
| `git clean -f` (without `-n`/`--dry-run`) | Permanently deletes untracked files. |
| `git checkout .`, `git checkout -- .`, `git restore .` | Discards working-tree changes. |
| `git rebase --no-verify` | Bypasses safety hooks. |
| `git branch -D main`, `git branch -D master` | Force-deletes a protected branch. |

A blocked destructive command suggests running it outside Claude Code if you
genuinely intend it.

## Known limitation: in-place writers and the cwd

The hook attributes a write to the file's own branch only when it can read the
target path from the command. For positional writers and redirects, it can. For
`sed -i`, `perl -i`, `curl -o`, `wget`, `truncate`, `dd of=`, `find -delete`,
`xargs rm`, and similar, the target is not recoverable positionally, so the hook
falls back to the branch of your shell's working directory.

The practical effect: `sed -i ... /path/to/main-repo/file.py` run from a feature
worktree is allowed, because the hook cannot confine the target and your shell is
not on a protected branch. Use `Edit`/`Write` for changes to a protected repo,
which are always judged by the file's branch.

## Disabling or scoping the hook

The hook honors the toolkit's configuration cascade. To turn it off, add its ID
to `disabled_hooks` in `~/.claude/natelandau-toolkit.toml` or your project's
`.claude/natelandau-toolkit.toml`:

```toml
disabled_hooks = ["branch-protection"]
```

See the toolkit configuration template at
`plugins/natelandau-toolkit/hooks/natelandau-toolkit.toml.example` for the full
set of options.
