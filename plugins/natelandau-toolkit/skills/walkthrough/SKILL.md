---
name: walkthrough
description: "Use when the user wants to see the UI or behavior an agent built (web, iOS, macOS, Android) without launching the app themselves: \"show me what you built\", \"demo this\", \"walk me through the UI\", \"screenshots of the change\", \"record the interaction\". Produces a local HTML page of stills and clips. Not for explaining how a change works in code."
disable-model-invocation: true
---

# Walkthrough

Capture stills and short clips of each front-end behavior you built into one local HTML
page. From the page alone, the user must be able to tell whether each behavior works and
looks right, and what you did not show.

## Skill files

Skill directory: `${CLAUDE_SKILL_DIR}`; scripts in `${CLAUDE_SKILL_DIR}/scripts/`. Only
this file shows the resolved absolute path. The references and the `run.sh` skeleton
write the placeholder `CLAUDE_SKILL_DIR`: substitute the absolute path in a command you
run; in `run.sh`, set it once at the top as the skeleton shows.

Read only the references for the platforms you capture:

| File | Read it when |
|---|---|
| `references/web.md` | The change touches a web UI. It also holds the before/after steps and the signed-in captures. |
| `references/ios.md` | The change touches an iOS app. |
| `references/macos.md` | The change touches a native macOS app. |
| `references/android.md` | The change touches an Android app. |
| `references/media.md` | Always. Names, encoding, and HTML for stills and clips. |
| `references/run-sh.md` | Always. The skeleton of `scripts/run.sh` and its cleanup. |

## When you stop for the user

Wait for the user at these points and no others:

1. **The scene plan**, before any capture. The user confirms or trims it. Name in the
   plan: the iOS simulator or Android virtual device the run installs on, and any
   project script that quits, replaces, or installs over a copy of the app. Switching
   to another device mid-run is a new stop of this kind: name the device and wait for
   a yes. Use a device the user already has, running or shut down. The
   install replaces any build of the app on it.
2. **A missing tool or permission** from preflight. Tool: show the install command and
   run it only on a yes. Permission: name the System Settings pane (for example
   **Privacy & Security > Screen Recording**), and skip that platform unless the user
   grants it and asks to continue.
3. **The focus notice**, once, before `run.sh` starts. `run.sh` can't pause mid-run, so
   name every step that can take focus: the macOS UI test or launch, a possible second
   macOS capture with the app in front when Stage Manager gives a thumbnail, bringing an
   off-screen window to the front for Peekaboo or region video, the region video (it
   records part of the real screen; keep clips short), and the Simulator window an iOS
   XCUITest run can open. Give a rough total of N seconds estimated from the steps. Wait
   until the user says start.
4. **Peekaboo**: a yes for each run, because it clicks and types in the real app and can
   bring it to the front.
5. **A sign-in scene with no test account**: ask for one.
6. **A sample flag that writes to the app's normal data store**: ask first; it changes
   the data of the user's own copy.
7. **A copy of the app already running**: ask the user to quit it. Never quit or signal
   it yourself. (Drivers stop a running app, and so do iOS and Android installs.)

If the app does not launch, end the run and report the error as the finding. No
workaround.

## Flow

### 1. Find the scope

Start from what the user asked you to build in the conversation. Then read the diff
(`git diff <default-branch>...HEAD` plus uncommitted changes) for UI changes the
conversation didn't mention. If the change is already on the default branch, read its
commits with `git show <sha>`.

### 2. Find the platforms

Only platforms the diff touches, not every platform in the repo.

### 3. Plan the scenes, then stop

A scene is one user-visible behavior. Per scene:

- Starting state.
- Steps.
- Stills or a clip (a clip only for motion or a sequence).
- Viewports or devices. Web defaults: desktop `1440x900`, mobile `390x844`.
- Whether a before/after applies (see "Before and after").

Show the plan and wait. Nothing slow runs until the user confirms or trims it.

### 4. Find the launch state

First read the project's agent instructions (`CLAUDE.md`, `AGENTS.md`) and task runner
(`justfile`, `Makefile`, `package.json` scripts). Use the project's own recipes for
worktrees, dev servers, builds, app launch and quit, seed data, and test accounts; this
skill's recipes are the fallback.

A project script can quit or replace a running copy of its app (for example, one that
installs a shared dev app and holds a lease on it). Use it as intended, but: do this
skill's running-app check before calling it (stop 7), name its effects in the plan
(stop 1), and run the project's matching quit or release command in cleanup. This
skill's rules still apply to every command it runs itself.

Find how the project reaches each starting state: dev-server command, seed data,
sample-mode launch arguments, test accounts. An unreachable starting state goes under
"Not shown" with the reason. Never use the user's real data, and never show a sign-in
wall in place of the scene.

### 5. Preflight and capture

Run preflight for the confirmed platforms. For macOS, make Screen Recording a required
check: `--screen` when a macOS still comes from `screencapture -l` (every still no UI
test takes); `--video` when a macOS scene needs a clip (includes `--screen`).

```bash
${CLAUDE_SKILL_DIR}/scripts/preflight.py web macos --screen
```

Exit `1`: a required tool or permission is missing; the install command or settings pane
is under each `MISSING` line. If the user declines, skip that platform and list its
scenes under "Not shown".

Write the capture files and `run.sh` into the walkthrough `scripts/` folder, run
`run.sh`, and let it encode the clips. Follow the platform references for each command.

### 6. Check every capture

Look at every still and every clip's poster frame. A spinner, an error, or the wrong
state fails. Retry once with a longer wait or a wait for an element; a second failure
goes under "Not shown" with the reason. Never present a bad capture as good.

### 7. Assemble and open the page

Write `index.html` per "The page", open it in the background, and print its absolute
path for later:

```bash
open -g <walkthrough-folder>/index.html
```

## Output folder

Read `../shared/output-dir.md` (relative to this skill's base directory) and follow it
with `<kind>` = `walkthroughs`. Each walkthrough gets a dated folder:

```text
<walkthroughs-dir>/YYYY-MM-DD-<slug>/
  index.html     the walkthrough page
  media/         stills, MP4 clips, and poster frames
  media/raw/     raw clips, deleted after each encode
  scripts/       storyboards, Maestro flows, WalkthroughTests.swift,
                 the web e2e capture spec, run.sh
  before-src/    temporary worktree for a web before/after, removed on exit
```

`run.sh` regenerates `media/` in one command. Capture files and media go only into this
folder. The run changes these things outside it:

- A temporary `WalkthroughTests.swift` copy in a UI test target, removed on exit.
- A temporary web e2e spec copy in the project's e2e folder, removed on exit, and the
  throwaway database the project's e2e run owns.
- Normal build output (Xcode DerivedData, Gradle `build/`, the web build folder),
  written as a user build would.
- The app on the iOS simulator or Android virtual device used, which belongs to the
  user; the install replaces any build on it (disclosed at stop 1).
- What a project script changes: a dev app installed to a fixed path, a lease it holds,
  a running copy it quits or replaces (disclosed at stop 1).

## Do not take over the screen

The user keeps working during captures. Every capture runs in the background and leaves
focus, mouse, and keyboard alone where the platform allows.

- Web: headless browsers only, never headed or `--interactive`.
- iOS: boot simulators with `xcrun simctl boot`. Never open Simulator.app or DeviceHub.
  `xcodebuild test` (XCUITest) can open the Simulator window (stop 3).
- Android: emulators with `-no-window`.
- macOS can't run fully in the background. Take stills first and put every macOS capture
  in one run. Start an app no UI test drives with the project's launch script or
  `open -g`. Stops 3 and 4 cover focus and Peekaboo.
- Open the finished page with `open -g` so the browser doesn't take focus.

## The page

One scrolling HTML page with inline CSS and a table of contents. No tabs for top-level
structure; the user must scroll and Cmd-F the whole page. Responsive for phones. Media
as relative files in `media/`, never base64. `references/media.md` has the HTML for
stills, clips, and side-by-side viewports.

Top of the page:

- A title and one paragraph summarizing the work in user terms.
- A scene index of thumbnails, each linked to its scene.
- **Coverage**: platforms and viewports captured, and a **Not shown** list with one
  reason per gap.

Per scene:

- A heading naming the behavior.
- How to reach it by hand: starting state and steps, in words.
- The media. Stills in a row, one caption per step. Clips as
  `<video controls muted loop playsinline poster=...>`. Different viewports or platforms
  side by side at the same step.
- **What to look for**: one or two sentences pointing at the changed detail.
- **Where it lives**: the scene's main files as plain paths. A pointer, not a code
  walkthrough.

Bottom of the page:

- The re-run command and its prerequisites.
- A capture log: tool versions, devices, simulator runtimes, date.

### Before and after

"Before" is the code without the change: the merge base of `HEAD` and the default
branch, or, if the change is already on the default branch (`HEAD` is the default
branch, or the change is a merged commit), its parent (`<sha>^`).

Capture a "before" only when straightforward: the commit checks out into a temporary
worktree and starts with the same command and launch state, with no migrations, new
seed data, or other setup. Otherwise write one sentence describing the old behavior.
The worktree steps in `references/web.md` are web only; iOS, macOS, and Android scenes
always get the one sentence, because building the "before" commit replaces the
installed app.

## Cleanup and failures

- `run.sh` cleans up on success and failure with `trap cleanup EXIT`: stops the dev
  servers and macOS app instances it started, shuts down simulators it booted, stops
  emulators it started, clears status-bar overrides, removes the XCUITest and e2e spec
  copies, and removes the before/after worktree. For a macOS app a project script
  launched, it runs the project's quit or release command. An app launched on a reused
  simulator or emulator keeps running after the run.
- Never stop a server, simulator, emulator, or app instance that was running before the
  run, and never erase app data.
- Failed scenes: keep the ones that captured; list the others under "Not shown" with the
  error.
- Unavailable platform (declined install, missing permission): skip it and note it under
  "Not shown".

## Privacy

Seed data, sample modes, and test accounts only. No test account for a sign-in scene:
ask the user for one. Never capture the user's own accounts, files, or data.

## Page text

Before assembling the page, invoke the `technical-writer` skill and follow it for every
piece of text in `index.html`: the summary, captions, steps, each "What to look for",
and each "Not shown" reason.
