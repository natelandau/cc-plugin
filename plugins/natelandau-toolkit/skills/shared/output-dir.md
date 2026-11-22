# Output directory

Write generated files for the user to a per-user cache directory outside the repo, so
nothing lands in version control and the repo is never changed to hide it. Substitute
the calling skill's `<kind>` (such as `explanations`) below.

## Choose the location

1. Cache root: `$XDG_CACHE_HOME` when set to an absolute path, else `$HOME/.cache`:

   ```bash
   case "${XDG_CACHE_HOME:-}" in
     /*) cache="$XDG_CACHE_HOME" ;;
     *)  cache="$HOME/.cache" ;;
   esac
   ```

2. Repo name: `basename "$(git rev-parse --show-toplevel)"`. In a worktree this is the
   worktree root, so each worktree gets its own folder. If the command fails (not a git
   repo), use `no-repo`.
3. `mkdir -p "$cache/natelandau-toolkit/<repo-name>/<kind>"`
4. Write the file there and tell the user its absolute path.

## Name the file

Prefix each file or folder name with today's date as `YYYY-MM-DD-`, for example
`~/.cache/natelandau-toolkit/<repo-name>/explanations/2026-07-08-explanation-<slug>.html`.

Never overwrite an existing entry (two repos can share a name). If the name is taken,
add `-2`, `-3`, and so on before the extension.
