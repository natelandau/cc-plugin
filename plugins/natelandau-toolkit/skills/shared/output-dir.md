# Output directory: shared location rule

A skill that writes a generated file for the user reads this document to decide
where the file goes. The file goes in a per-user cache directory outside the
repo, so it never lands in version control and the skill never changes the
repo to hide it. The cache survives a reboot, so the user can open the file, or
run a saved script, again later.

The calling skill picks a `<kind>` name for its output, such as `explanations`.
Replace `<kind>` below with that name.

## Choose the location

1. Find the cache root. Use `$XDG_CACHE_HOME` when it is set to an absolute
   path. Otherwise use `$HOME/.cache`:

   ```bash
   case "${XDG_CACHE_HOME:-}" in
     /*) cache="$XDG_CACHE_HOME" ;;
     *)  cache="$HOME/.cache" ;;
   esac
   ```

2. Find the repo name, the last path component of the repo root:

   ```bash
   basename "$(git rev-parse --show-toplevel)"
   ```

   In a git worktree, the repo root is the root of that worktree, so each
   worktree gets its own folder. If the command fails, the directory is not in
   a git repo. Use `no-repo` as the repo name.
3. Make the target directory, and its parents, if it does not exist:

   ```bash
   mkdir -p "$cache/natelandau-toolkit/<repo-name>/<kind>"
   ```

4. Write the file into the target directory. Tell the user its absolute path.

## Name the file

Start each file or folder name with today's date as `YYYY-MM-DD-`, so the
entries sort by time. For example:
`~/.cache/natelandau-toolkit/<repo-name>/explanations/2026-07-08-explanation-<slug>.html`.

Two repos can share a name, so never overwrite an entry that already exists.
If the name is taken, add `-2`, `-3`, and so on before the extension.
