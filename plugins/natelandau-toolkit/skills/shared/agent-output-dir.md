# Agent output directory: shared location rule

A skill that writes a generated file for the user reads this document to decide
where the file goes. The file stays inside the repo, so the user can find it
next to the code. Git ignores it, so it never lands in version control.

The calling skill picks a `<kind>` name for its output, such as `explanations`.
Replace `<kind>` below with that name.

## Choose the location

1. Find the repo root:

   ```bash
   git rev-parse --show-toplevel
   ```

   In a git worktree, the repo root is the root of that worktree. Each worktree
   has its own `.agent/` directory.
2. If the command fails, the directory is not in a git repo. Create a temp
   directory with `mktemp -d`, write the file there, and tell the user the
   final path. Skip the steps below.
3. Make the target directory `<repo-root>/.agent/<kind>/`. Create it, and
   `.agent/`, if they do not exist. The directory must exist before the next
   step, because the pattern `.agent/` matches only a directory.
4. Make sure that git ignores `.agent`. Always run git with `-C` and the repo
   root, because `git check-ignore` reads its path relative to the current
   directory:

   ```bash
   git -C "<repo-root>" check-ignore -q .agent
   ```

5. Read the exit code:
   - 0: git ignores `.agent`. Go to step 7.
   - 1: git does not ignore `.agent`. Go to step 6.
   - Any other code: the check failed. Stop, and report the error to the
     user. Do not edit `.gitignore`, and do not write the file.
6. Append `.agent/` to `<repo-root>/.gitignore` on its own line. Create the
   file if it does not exist. If the file does not end with a newline, add one
   first. Tell the user that you changed `.gitignore`.
7. Write the file into the target directory.

Do the ignore check every time. A repo can lose its `.gitignore` entry between
runs.

## Name the file

Start each file or folder name with today's date as `YYYY-MM-DD-`, so the
entries sort by time. For example:
`.agent/explanations/2026-07-08-explanation-<slug>.html`.
