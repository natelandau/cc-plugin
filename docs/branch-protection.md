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

The hook follows each `cd <path>` in a command, also one after a background job
(`sleep 1 & cd <path> && rm app.py`). A `cd` that runs in a subshell
(`cd <path> &`, or `cd <path> | ...`) does not change the directory for the
statements after it.

## Exempt paths

Some directory trees are working stores you and your agents commit to on their
default branch by design, so there is no trunk hygiene to protect in them. Every
protected-branch rule on this page is waived for paths inside such a tree.

You declare them, in either of two places. Both are read and the results are
combined, so you can use whichever fits or both.

**Your global config**, `~/.claude/natelandau-toolkit.toml`:

```toml
exempt_paths = [
  "~/repos/shared-context-vault",
  "/Volumes/scratch/notes",
]
```

**An environment variable**, `NATELANDAU_TOOLKIT_EXEMPT_PATHS`, holding a
`:`-separated list. Use it for a root that differs per machine or is composed
from another variable:

```bash
export NATELANDAU_TOOLKIT_EXEMPT_PATHS="$SHARED_CONTEXT_VAULT:$HOME/scratch"
```

A leading `~` is expanded in both. Two cautions about the variable. Hooks inherit
the environment Claude Code was started with, so an export in your shell profile
does not apply if you launch Claude Code from a GUI launcher rather than a
terminal; the config file has no such gap. And anything that sets the variable in
that environment declares an exempt tree, including a repository's own `.envrc`
picked up by `direnv` before you start a session, so treat allowing a `direnv`
environment as trusting that repository with the carve-out.

**`exempt_paths` is read from the global config only.** A project's
`.claude/natelandau-toolkit.toml` is a committed file inside the very repository
branch protection is guarding, so honoring the key there would let a repo waive
the guard for everyone who clones it. The key is silently ignored in a project
config.

The exemption is keyed off the path, like every other rule. An edit to a file in
an exempt tree passes from any shell, a `git -C <exempt-tree> commit` passes from
anywhere, and an edit to some other repo on `main` is still blocked even while
your shell sits inside one.

Two things it does not waive:

- **Destructive operations.** A force push or a `git reset --hard` inside an
  exempt tree is still blocked. Those destroy work whatever branch they run on.
- **Anything, when an entry is unusable.** An empty, relative, or `/` entry, a
  `~user` naming no account, and any path carrying a `..` segment each
  contribute no root and are dropped on their own, leaving neighbors intact, so
  a typo narrows the exemption rather than widening it or voiding the list.

The `commit-message` hook reads the same two sources, so commits and PR titles
aimed at an exempt tree also skip the conventional-commit format check.

## Git operations

The table covers git actions aimed at a protected branch. Actions on a feature
branch, or inside an exempt tree, are unaffected by branch protection
(destructive operations are the exception; see below).

| Action | Decision | Why |
| --- | --- | --- |
| `git status`, `git log`, `git diff`, other read-only git | Allow | Reads never change history. |
| `git commit` on a protected branch | Block | A direct commit to trunk is almost always a "forgot to branch" mistake. |
| `git commit --dry-run` | Allow | A dry run reports what a commit would do and writes nothing. |
| `git commit` from inside a linked worktree | Allow | Worktrees are the supported path for isolated work. |
| `git commit` finishing a squash merge (`git merge --squash X && git commit`) | Allow | The follow-up commit is expected; the merge staged the changes. |
| `git merge`, `git merge --no-ff`, `git pull` (a real merge commit) | Ask | A merge onto trunk is sometimes a deliberate, human-approved integration. You approve or reject. |
| `git merge --ff-only`, `git merge --squash`, `git merge --abort`, `git merge --quit` | Allow | These cannot write a merge commit to the branch. |
| `git pull --ff-only`, `git pull --rebase`, `git pull -r` | Allow | Fast-forward or rebase, no merge commit. |
| `git apply`, `git am`, `git stash pop`, `git stash apply`, `git rm`, `git mv`, `git restore <path>`, `git checkout [<commit>] -- <path>` | Block | These change tracked files in the working tree, the same as an edit on trunk. |
| `git restore --staged <path>` (without `--worktree`), `git rm --cached`, `git rm -n`, `git mv -n`, `git stash` (also `push`, `save`, `list`, `show`) | Allow | These change only the index, do a dry run, only read, or park uncommitted edits where they stay recoverable. |
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
| In-place and download writers | `sed -i` and `gsed -i` (also `-Ei`, BSD `-I`, `--in-place` and its prefixes such as `--in`), `perl -i` (also `-pi`), `curl -o`/`-O`, `wget`, `tee` |
| Bulk and in-place writers without a positional target | `truncate`, `dd of=<path>` (except `of=/dev/null`), `find ... -delete`, `xargs rm` |

The command name is read past a leading launcher (`sudo`, `env`, `command`,
`nice`, `time`), an absolute path (`/bin/rm`), or a subshell/group opener
(`( rm ... )`), so these do not slip the rules. Metacharacters inside quotes are
treated as data, not syntax, so a quoted program like `awk 'c>=2'` or
`grep 'a>b'` is not mistaken for a redirect.
A flag or force refspec written as a whole quoted word (`sed "-i"`,
`git push '-f'`, `git push origin '+main'`) is read as
the plain flag, because the shell removes the quotes.

The mode operand of `chmod` (`755`, `+x`, `u+x,go-w`) and the owner operand of
`chown` (`nate:staff`) are not write targets. Only the files after them are
checked. Thus `chmod +x /path/to/feature-repo/run.sh` is judged by the branch of
the feature repository, not by the branch of your shell's directory.

For `cp`, `ln`, and `install`, only the destination is a write target: the
`-t`/`--target-directory` value, else the last operand. The sources are only
read, so `cp /path/to/main-repo/app.py /tmp/app.py` is allowed. A lone `ln`
operand creates a link in your shell's directory, and `install -d` creates every
operand. The values of options such as `install -m 755` are not paths. If the
hook cannot parse the options, it checks every operand. The hook also checks
every operand when the destination contains `$`, a backtick, a glob, or a brace
list, because the shell changes such a word before the command runs.

For every write command, an fd duplication (`2>&1`, `>&2`), an input redirect
(`< file`, `<<< text`), and an unquoted comment (`# note`) are not operands.
Thus `rm /tmp/scratch 2>&1` does not read `2>&1` as a file in your directory.

The hook reads a flag only from the pipeline stage that runs the command. In
`sed -n 1,80p app.ts | grep -i video`, the `-i` belongs to `grep`, so the
command is a read and is allowed. A writer in any stage is checked against its
own targets. Thus `cat list | sed -i 's/a/b/' app.py` is blocked, and
`echo y | rm /path/to/main-repo/app.py` is blocked from any directory. A `|&`
pipe and a `&` that runs a command in the background also end a stage. The `&`
of a redirect (`2>&1`, `>&2`, `&>file`) does not.

The body of a command substitution (`$( )`, backticks) or a process
substitution (`<( )`) runs, so the hook checks it as a command of its own. This
applies inside double quotes too. Thus `echo "$(rm app.py)"` is blocked on a
protected branch. A write command whose operand is a substitution
(`cp a $(echo /repo/app.py)`) is checked against each path that the
substitution mentions.

A pipe inside a command substitution (`$( )`, backticks) or a process
substitution (`<( )`) does not end the stage. Thus the `-i` in
`sed -e $(echo s/a/b/ | cat) -i app.py` belongs to `sed`, and the command is
blocked.

A git command gets the same file-write checks as any other command. Thus
`git show HEAD:app.py > app.py`, `git ls-files | xargs rm`, and
`git diff | tee app.py` are blocked. A git commit or merge in a later pipeline
stage gets the git checks.

The hook does not check a heredoc body as commands when a known data sink reads
it. Thus the text of a file written with `cat > notes.md <<'EOF'` is not checked
line by line. The data sinks are:

- A single `cat` or `tee` command, optionally after a bare `sudo` or `env`.
- A non-shell interpreter: `python3 -`, `node`, `ruby`, or `perl`.
- A commit or PR message command, such as `git commit -F -`.

For a sink, nothing can follow the heredoc on its line except redirects: no
pipe, list, background `&`, or substitution. No later line can mention a file
that the heredoc writes, as in `bash /tmp/s.sh`. For any other consumer, the
hook checks the body as commands, because the consumer can run it as shell
(`sh`, `su`, `sudo -s`, `script`, `exec 3<<`, `$SHELL`). The command that opens
the heredoc is always checked, so `cat > app.py <<'EOF'` is blocked. If a data
sink reads a heredoc with an unquoted tag (`<<EOF`), the shell runs the `$( )`
and backtick substitutions in the body. The hook checks those substitutions as
commands and treats the other lines as data.

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
branch unless the target file is gitignored or inside an exempt tree.

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
`xargs rm`, and similar, the target is not
recoverable positionally, so the hook falls back to the branch of your shell's
working directory.

The practical effect: `sed -i ... /path/to/main-repo/file.py` run from a feature
worktree is allowed, because the hook cannot confine the target and your shell is
not on a protected branch. Use `Edit`/`Write` for changes to a protected repo,
which are always judged by the file's branch.

The hook recognizes command shapes, so it cannot see a write made by an
executable it does not model. An inline interpreter program (`python3 -c`,
`python3 - <<EOF`, `node -e`), a script file (`python3 /tmp/tool.py`), a
formatter (`ruff format`, `prettier --write`), `pre-commit run`, `make`, or an
`npm run` script can still modify tracked files on a protected branch. What
these write is decided by the program, not the command line, so the hook does
not try to guess. A redirect on the same command (`python3 -c ... > file`) is
still checked like any other.

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
