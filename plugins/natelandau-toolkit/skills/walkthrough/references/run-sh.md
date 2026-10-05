# run.sh

This file gives the skeleton of `scripts/run.sh`. The script regenerates
`media/` with one command, both for you during the capture and for the user
later. Copy the skeleton, keep its cleanup and helpers, and replace the example
server and capture steps with the steps of this walkthrough.

## Requirements

- `set -euo pipefail` at the top.
- One `cleanup` function on `trap ... EXIT`. It stops only what the script
  started: servers by PID, a simulator that it booted, the status-bar override,
  the XCUITest copy, the e2e spec copy, a clip file on an Android device, an
  emulator that it started, the before/after worktree, and a macOS app that a
  project launch script started, through that script's quit command.
- Each capture step writes into `../media/`, and each raw clip into
  `../media/raw/`.
- The last step runs `encode.py` on every raw clip.
- The script runs with the macOS system bash (3.2). Do not use `mapfile`,
  associative arrays, or `${var,,}`.

## The skill path and the project root

`${CLAUDE_SKILL_DIR}` is not an environment variable. Claude Code replaces it
only in the text of SKILL.md. Set it as a shell variable at the top of
`run.sh` to the absolute skill directory that SKILL.md shows. The script then
works when the user runs it later in a plain terminal.

Write the project root into `REPO` the same way, as an absolute path. Do not
compute it with `git rev-parse`. That command fails, and stops the script,
when the project is not in a git repo.

## Skeleton

```bash
#!/usr/bin/env bash
# Regenerates ../media for this walkthrough. Usage: ./run.sh
set -euo pipefail

# Absolute path of the walkthrough skill, written in when this file was made.
# A plugin update moves it. If the scripts below are missing, update this line.
CLAUDE_SKILL_DIR="/ABSOLUTE/PATH/TO/skills/walkthrough"
# Absolute path of the project root, written in when this file was made.
REPO="/ABSOLUTE/PATH/TO/project"

HERE="$(cd "$(dirname "$0")" && pwd)"
MEDIA="$(cd "$HERE/.." && pwd)/media"
RAW="$MEDIA/raw"
mkdir -p "$RAW"
cd "$HERE"

# Everything this script starts. The cleanup touches nothing else.
PIDS=()
BOOTED_UDID=""
STATUS_BAR_UDID=""
EMULATOR_SERIAL=""
XCUI_COPY=""
E2E_SPEC_COPY=""
MAC_LAUNCHED=""
DEVICE_CLIP=""
DEVICE_CLIP_SERIAL=""
BEFORE_DIR=""
FAILED=()

kill_tree() {
  local pid=$1 child
  for child in $(pgrep -P "$pid"); do kill_tree "$child"; done
  kill -TERM "$pid" 2>/dev/null || true
}

# Call after `wait` on a short-lived process, so the cleanup never signals a reused PID.
forget_pid() {
  local gone=$1 pid kept=()
  for pid in ${PIDS[@]+"${PIDS[@]}"}; do [[ "$pid" == "$gone" ]] || kept+=("$pid"); done
  PIDS=(${kept[@]+"${kept[@]}"})
}

cleanup() {
  local status=$?
  set +e
  for pid in ${PIDS[@]+"${PIDS[@]}"}; do kill_tree "$pid"; done
  [[ -n "$XCUI_COPY" ]] && rm -f "$XCUI_COPY"
  [[ -n "$E2E_SPEC_COPY" ]] && rm -f "$E2E_SPEC_COPY"
  # Replace with the project's quit or release command for its macOS app.
  [[ -n "$MAC_LAUNCHED" ]] && (cd "$REPO" && PROJECT_QUIT_COMMAND)
  [[ -n "$STATUS_BAR_UDID" ]] && xcrun simctl status_bar "$STATUS_BAR_UDID" clear
  [[ -n "$BOOTED_UDID" ]] && xcrun simctl shutdown "$BOOTED_UDID"
  [[ -n "$DEVICE_CLIP" ]] && adb -s "$DEVICE_CLIP_SERIAL" shell rm -f "$DEVICE_CLIP"
  [[ -n "$EMULATOR_SERIAL" ]] && adb -s "$EMULATOR_SERIAL" emu kill
  [[ -n "$BEFORE_DIR" ]] && git -C "$REPO" worktree remove --force "$BEFORE_DIR"
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

# Maestro sends anonymous analytics and prints a notice on each run by default.
export MAESTRO_CLI_NO_ANALYTICS=1 MAESTRO_CLI_ANALYSIS_NOTIFICATION_DISABLED=true

port_in_use() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }

wait_for_url() {
  local url=$1 tries=${2:-240} i
  for ((i = 0; i < tries; i++)); do
    curl -sf -o /dev/null "$url" 2>/dev/null && return 0
    sleep 0.5
  done
  echo "Timed out waiting for $url" >&2
  return 1
}

# A failed step is reported at the end, and the other steps still run.
step() {
  local name=$1
  shift
  echo "== $name"
  if ! "$@"; then
    echo "FAILED: $name" >&2
    FAILED+=("$name")
  fi
}

# --- Start what the captures need ---------------------------------------------
PORT=5199
if port_in_use "$PORT"; then
  echo "Port $PORT is in use. Pick another port." >&2
  exit 1
fi
(cd "$REPO" && exec npm run dev -- --port "$PORT" >"$RAW/server.log" 2>&1) &
PIDS+=("$!")
wait_for_url "http://localhost:$PORT/"

# --- Captures -------------------------------------------------------------------
# `step` calls these inside `if`, where errexit is off. `|| return 1` stops a scene
# at its first failed command.
capture_settings() {
  shot-scraper multi shots.yml || return 1
}

capture_add_item() {
  shot-scraper video 03-add-item.yml || return 1
  shot-scraper video 03-add-item-mobile.yml || return 1
}

step "01 settings stills" capture_settings
step "03 add item clip" capture_add_item

# --- Encode raw clips -------------------------------------------------------------
for clip in "$RAW"/*.webm "$RAW"/*.mov "$RAW"/*.mp4; do
  [[ -e "$clip" ]] || continue
  if "${CLAUDE_SKILL_DIR}/scripts/encode.py" "$clip" --out-dir "$MEDIA"; then
    rm -f "$clip"
  else
    FAILED+=("encode $(basename "$clip")")
  fi
done

if ((${#FAILED[@]})); then
  echo "Failed steps:" >&2
  printf '  %s\n' "${FAILED[@]}" >&2
  exit 1
fi
echo "Done: $MEDIA"
```

## Adapt the skeleton

- Delete the cleanup variables and cleanup lines that this walkthrough does
  not use, for example the `MAC_LAUNCHED` line when no project script
  launches a macOS app.
- Set each cleanup variable at the moment the script creates that thing, and
  never before. If the run fails early, the cleanup then skips what does not
  exist yet. Leave a variable empty for something that was already running.
- Add the PID of every background process to `PIDS` when you start it.
  `kill_tree` also stops the child processes, which a wrapper such as `npm run
  dev` starts. A server stays in `PIDS` until the cleanup. For a short-lived
  process, such as `simctl recordVideo`, `adb shell screenrecord`, or a
  background UI test, call `forget_pid` right after its `wait`. Otherwise the
  cleanup can signal an unrelated process that reuses the PID.
- Give every wait loop a limit. A loop that waits for a file, a log line, a
  window, or a boot stops after a fixed number of tries, and then fails.
- If `run.sh` starts the dev server, do not also put a `server:` key in the
  `shot-scraper` YAML files.
- Put each scene into a capture function, and run it with `step`, so one
  failed scene does not stop the others. List each failed step under "Not
  shown" in the page, with its error.
- Inside a capture function, errexit is off, because `step` calls the function
  inside `if`. End each command that can fail with `|| return 1`, or chain the
  commands with `&&`. Without this, a failed command does not stop the scene,
  and the step reports success.
- Keep the setup commands outside `step`. If the server or the app cannot
  start, the run must stop, because that failure is the finding.

## Run it

Run the script from any directory:

```bash
.agent/walkthroughs/2026-10-05-add-item/scripts/run.sh
```

If it exits with `1`, read the failed steps at the end of its output. After
each run, make sure that no process from the run is still alive, for example
with `lsof -nP -iTCP:5199 -sTCP:LISTEN`.
