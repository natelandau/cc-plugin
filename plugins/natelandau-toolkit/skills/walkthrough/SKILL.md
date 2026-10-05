---
name: walkthrough
description: "Use when the user wants to see the UI or behavior an agent built, instead of launching the app and clicking through it themselves. Trigger on requests like \"show me what you built\", \"demo this\", \"walk me through the UI\", \"screenshots of the change\", \"record the interaction\", or /walkthrough. Captures stills and short clips of web, iOS, macOS, and Android front ends from the local build, in the background where the platform allows, and assembles them into a local HTML walkthrough with a one-command re-run script. Runs only on request, because captures are slow. Does not explain code: a request to understand how a change works, rather than what it does on screen, is not a walkthrough."
---

# Walkthrough

The user wants to see the front-end work that you built, without launching the
app themselves. You capture stills and short clips of each built behavior and
put them into one local HTML page. From that page alone, the user must be able
to tell whether each behavior works and looks right, and what you did not show.

## Skill files

The skill directory is `${CLAUDE_SKILL_DIR}`. The scripts are in
`${CLAUDE_SKILL_DIR}/scripts/`. Only this file shows the resolved absolute path.
The reference files and the `run.sh` skeleton write the skill directory as the
placeholder `CLAUDE_SKILL_DIR` in shell-variable form. In a command that you
run, replace that placeholder with the absolute path above. In `run.sh`, set it
once as a shell variable at the top, as the skeleton shows.

Read only the references for the platforms that you capture:

| File | Read it when |
|---|---|
| `references/web.md` | The change touches a web UI. It also holds the before/after steps and the signed-in captures. |
| `references/ios.md` | The change touches an iOS app. |
| `references/macos.md` | The change touches a native macOS app. |
| `references/android.md` | The change touches an Android app. |
| `references/media.md` | Always. Names, encoding, and HTML for stills and clips. |
| `references/run-sh.md` | Always. The skeleton of `scripts/run.sh` and its cleanup. |

## When you stop for the user

The run waits for the user at these times, and at no other time:

1. The scene plan, before any capture. The user confirms or trims it. If the
   run installs the app on an iOS simulator or an Android virtual device, name
   that device in the plan. The run uses a device that the user already has,
   running or shut down, and the install replaces any build of the app that
   the user had on it. If the run uses a project script that quits, replaces,
   or installs over a copy of the app, name that behavior in the plan too.
   If the run must switch to another device during the run, that switch is
   a new stop of this kind: name the device, and wait for a yes.
2. A tool or permission that preflight reports as missing. For a tool, show
   the install command, and run it only after the user says yes. For a
   permission, name the System Settings pane, for example **Privacy &
   Security > Screen Recording**. Skip that platform unless the user grants the
   permission and asks you to continue.
3. The focus notice, once, before `run.sh` starts. `run.sh` cannot pause in
   the middle of a run, so name every step that can take focus in this one
   notice: the macOS UI test or launch, a possible second macOS capture with
   the app in front when Stage Manager gives a thumbnail, bringing an
   off-screen window to the front for Peekaboo or for region video, the
   region video, and the Simulator window that an iOS XCUITest run can open.
   Give a rough total of N seconds, with N estimated from the steps. Wait
   until the user says to start.
4. Peekaboo. Get the user's yes for each run, because Peekaboo clicks and
   types in the real app, and it can bring the app to the front.
5. A scene that needs a sign-in, when you find no test account. Ask for one.
6. A sample flag that writes into the app's normal data store. Ask before you
   use it, because it changes the data of the user's own copy of the app.
7. A copy of the app that is already running. Stop and ask the user to quit
   it. Never quit or signal it yourself.

If the app does not launch, the run ends. Report the error, because that
failure is the finding. Do not look for a way around it.

## Flow

### 1. Find the scope

Start from the conversation: what did the user ask you to build? Then read the
diff, `git diff main...HEAD` plus the uncommitted changes, to find UI changes
that the conversation did not mention. If the default branch is not `main`, use
the default branch. If the change is already on the default branch, read the
commits of the change with `git show <sha>` instead.

### 2. Find the platforms

Choose the platforms from the files that the diff touches, not from all the
platforms that the repo contains. A web-only change in a repo with an iOS app
gets only web captures.

### 3. Plan the scenes, then stop

A scene is one behavior that a user can see. For each scene, write down:

- The starting state.
- The steps.
- Stills or a clip. Use a clip only when the behavior is motion or a sequence.
- The viewports or devices. The web defaults are desktop `1440x900` and mobile
  `390x844`.
- Whether a before/after applies. See "Before and after".

Show the plan to the user and wait. Nothing slow runs until the user confirms or
trims the plan.

### 4. Find the launch state

First read the project's agent instructions (`CLAUDE.md`, `AGENTS.md`) and its
task runner (`justfile`, `Makefile`, `package.json` scripts). Use the project's
own recipes for worktrees, dev servers, builds, app launch and quit, seed data,
and test accounts. The recipes in this skill are the fallback when the project
has none.

A project script can quit or replace a running copy of its app, for example a
script that installs one shared dev app and holds a lease on it. Use that
script as the project intends, with these limits:

- Before you call the script, do the running-app check of this skill. If a
  copy of the app runs, stop and ask the user to quit it.
- Name what the script quits, replaces, or installs in the scene plan (stop
  1 in "When you stop for the user").
- In the cleanup, run the matching quit or release command of the project.

The rules of this skill still apply to every command that the skill itself
runs.

Then find how the project reaches each starting state: its dev-server command,
seed data, sample-mode launch arguments, and test accounts. If you cannot reach
a starting state, put that scene under "Not shown" with the reason. Never use
the user's real data, and never show a sign-in wall in place of the scene.

### 5. Preflight and capture

Run the preflight for the confirmed platforms. For macOS, add a flag that makes
Screen Recording a required check:

- Add `--screen` when a macOS still comes from `screencapture -l`, which is
  every still that no UI test takes.
- Add `--video` when a macOS scene needs a clip. `--video` includes the
  `--screen` check.

```bash
${CLAUDE_SKILL_DIR}/scripts/preflight.py web macos --screen
```

Exit code `1` means that a required tool or permission is missing. The output
shows the install command or the settings pane under each `MISSING` line. If
the user declines, skip that platform and list its scenes under "Not shown".

Then write the capture files and `run.sh` into the walkthrough `scripts/`
folder, run `run.sh`, and let it encode the clips. Follow the platform
references for each command.

### 6. Check every capture

Look at every still, and at the poster frame of every clip. A capture fails the
check when it shows a spinner, an error, or the wrong state. Give a failed
capture one retry with a longer wait or a wait for an element. If the retry also
fails, move the capture to "Not shown" with the reason. Never present a bad
capture as a good one.

### 7. Assemble and open the page

Write `index.html` as "The page" describes. Then open it in the background
from the walkthrough folder that "Output folder" chose. In a git repo, that
folder is usually `<repo-root>/.agent/walkthroughs/<YYYY-MM-DD-slug>/`:

```bash
open -g <walkthrough-folder>/index.html
```

Print the absolute path of `index.html`, so the user can open it again later.

## Output folder

Read `../shared/agent-output-dir.md` (relative to this skill's base directory)
and follow it with `<kind>` set to `walkthroughs`. Each walkthrough gets its own
dated folder:

```text
.agent/walkthroughs/YYYY-MM-DD-<slug>/
  index.html     the walkthrough page
  media/         stills, MP4 clips, and poster frames
  media/raw/     raw clips, deleted after each encode
  scripts/       storyboards, Maestro flows, WalkthroughTests.swift,
                 the web e2e capture spec, run.sh
  before-src/    temporary worktree for a web before/after, removed on exit
```

`run.sh` regenerates `media/` with one command, so the user can run it again
later. The capture files and the media go only into the walkthrough folder.
The run changes these things outside it:

- The `.gitignore` line that the output-folder rule adds.
- The temporary copy of `WalkthroughTests.swift` that `run.sh` puts into a UI
  test target and removes on exit.
- The temporary copy of a web e2e spec that `run.sh` puts into the project's
  e2e folder and removes on exit, and the throwaway database that the
  project's e2e run owns.
- The normal build output of the project, such as Xcode DerivedData, Gradle
  `build/` folders, and the output folder of a web build. A build writes there
  as it does when the user builds.
- The app on the iOS simulator or Android virtual device that the run uses.
  That device belongs to the user, whether it was running or shut down, and
  the install replaces any build of the app that the user had on it. Stop 1
  in "When you stop for the user" discloses this install.
- What a project script changes when the run uses it, for example a dev app
  that it installs to a fixed path, a lease that it holds, or a running copy
  that it quits or replaces. Stop 1 discloses this too.

## Do not take over the screen

The user keeps working while the captures run. Every capture runs in the
background and leaves the focus, the mouse, and the keyboard alone, where the
platform allows it.

- Web: use headless browsers only. Never use a headed or `--interactive` mode.
- iOS: boot simulators with `xcrun simctl boot`. Never open Simulator.app or
  DeviceHub.
- Android: start emulators with `-no-window`.
- macOS: this platform cannot run fully in the background. Take stills first,
  and put every macOS capture into one run. Start an app that no UI test drives
  with the project's launch script, or with `open -g`. Stops 3 and 4 in "When
  you stop for the user" cover the focus notice and Peekaboo.
- iOS XCUITest: `xcodebuild test` can open the Simulator window. Stop 3 covers
  it.
- In the focus notice, tell the user that macOS region video records part of
  the real screen. Keep each clip short.
- Open the finished page with `open -g`, so the browser does not take focus.

## The page

Write one scrolling HTML page with inline CSS and a table of contents. Do not use
tabs for the top-level structure, because the user must scroll the whole page and
search it with Cmd-F. Make it responsive, so it reads on a phone. Reference media
as relative files in `media/`, never as base64. `references/media.md` gives the
HTML for stills, clips, and side-by-side viewports.

At the top of the page:

- A title, and one paragraph that summarizes the work in user terms.
- A scene index of thumbnails, each linked to its scene.
- **Coverage**: the platforms and viewports that you captured, and a **Not
  shown** list with one reason for each gap.

For each scene:

- A heading that names the behavior.
- How to reach it by hand: the starting state and the steps, in words.
- The media. Put stills in a row with a caption for each step. Embed clips as
  `<video controls muted loop playsinline poster=...>`. Put the captures of
  different viewports or platforms side by side at the same step.
- **What to look for**: one or two sentences that point at the changed detail.
- **Where it lives**: the main files for the scene, as plain paths. This is a
  pointer, not a code walkthrough.

At the bottom of the page:

- The re-run command and its prerequisites.
- A capture log: tool versions, devices, simulator runtimes, and the date.

### Before and after

The "before" is the code without the change. It is the merge base of `HEAD`
and the default branch. If the change is already on the default branch,
because `HEAD` is the default branch or the change is a merged commit, the
"before" is the parent of the change (`<sha>^`).

Show a "before" capture only when it is straightforward. That means the
"before" commit checks out into a temporary worktree and starts with the same
command and launch state, with no migrations, new seed data, or other setup.
Otherwise, write one sentence that describes the old behavior.

The worktree steps in `references/web.md` cover web only. For an iOS, macOS, or
Android scene, write the one-sentence "before", because a build of the "before"
commit replaces the installed app.

## Cleanup and failures

- `run.sh` cleans up on success and on failure with `trap cleanup EXIT`. It
  stops the dev servers and the macOS app instances that it started, shuts
  down the simulators that it booted, stops the emulators that it started,
  clears the status-bar overrides, removes the XCUITest copy and the e2e spec
  copy, and removes the before/after worktree. For a macOS app that a project
  script launched, it runs the project's quit or release command. An app that
  the run launched on a reused simulator or emulator keeps running after the
  run.
- Never stop a server, simulator, emulator, or app instance that was running
  before the run, and never erase app data. If the app already runs, stop and
  ask the user to quit it. The drivers stop a running app, and so does the
  install on iOS and Android.
- If some scenes fail, keep the scenes that captured. List the others under "Not
  shown" with the error.
- If a platform is not available, for example because of a declined install or a
  missing permission, skip it and note it under "Not shown".
- If the app does not launch, the run ends. See "When you stop for the user".

## Privacy

Use seed data, sample modes, and test accounts only. If a scene needs a sign-in
and the project has no test account, ask the user for one. Never capture the
user's own accounts, files, or data.

## Always pair with technical-writer

This skill covers the mechanics of the walkthrough: what to capture, how to
capture it without taking over the screen, and how to build the page. Writing
quality lives in the `technical-writer` skill. Before you assemble the page,
invoke `technical-writer`, and follow it for every piece of text that you write
into `index.html`: the summary, the captions, the steps, each "What to look
for", and each "Not shown" reason.
