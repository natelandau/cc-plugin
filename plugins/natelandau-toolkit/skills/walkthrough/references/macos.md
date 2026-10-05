# macOS captures

This file tells you how to capture stills and clips of a native macOS app.
macOS is the one platform that cannot run fully in the background: XCUITest
activates the app, and region video records the real screen. Keep that time
short, and tell the user before it starts.

`${CLAUDE_SKILL_DIR}` in the commands below is not an environment variable.
Replace it with the absolute skill directory that SKILL.md shows.

## Rules

- Take stills first. Record video only when the user asks for it.
- Put every macOS capture into one run, so the app takes focus once.
- Before the run, tell the user that the app will take focus for roughly N
  seconds, so they can pause their work. Estimate N from the number of steps.
  `run.sh` cannot pause in the middle of a run, so this one notice names every
  step that can take focus. That includes the possible second capture in step
  8 of "Stills without a UI test", and bringing an off-screen window to the
  front for Peekaboo or region video.
- Start an app that no UI test drives with the project's launch script, or
  with `open -g`, so it opens in the background. "Launch with a project
  script" comes first.
- Never quit or signal an instance of the app that the user runs. Make sure
  that the app is not running before a UI test or an `open -g` launch.
- Never add a UI test target, and never edit `project.pbxproj`.
- Use Peekaboo only after the user says yes for this run. It clicks and
  types in the real app, and an off-screen window must come to the front,
  which takes focus.

## Choose the method

Search `project.pbxproj` for these two strings:

- `com.apple.product-type.bundle.ui-testing` marks a UI test target.
- `PBXFileSystemSynchronizedRootGroup` marks an Xcode 16 synchronized folder.
  Make sure that the UI test target lists one in `fileSystemSynchronizedGroups`.

A UI test target with a synchronized folder is a usable UI test target. Pick
the method from the table:

| Scene needs | Usable UI test target | No usable UI test target |
|---|---|---|
| Launch state only | XCUITest attachments | `open -g` with launch flags, then `screencapture -l` |
| Clicks or typing | XCUITest attachments | Peekaboo with a yes, then `screencapture -l` |
| Video, on request | `screencapture -v` during the UI test | `screencapture -v` during the Peekaboo run, with a yes |

If the project has no usable UI test target, tell the user that a UI test
target is a one-time setup. It gives stills of every step with no cursor and
no Screen Recording permission. Do not add the target yourself.

If the user does not say yes to Peekaboo, capture the launch-state stills, and
put only the scenes that need input under "Not shown" with the reason.

## Find the launch state

Search the app for DEBUG launch flags that start it in a sample state, such as
`-SampleShell`. Look for `ProcessInfo.processInfo.arguments`, launch-time
`UserDefaults` keys, and `#if DEBUG` blocks.

A debug build with the same bundle identifier reads the same container as the
user's copy of the app. The sample flag must keep its sample data in a store
apart from the user's data. Each scene starts with the data that the earlier
scenes left. Order the scenes to match, or reset the sample data with the
app's own sample flag. If the flag writes into the normal store, ask the user
before you use it.

## Stills with XCUITest

1. Write `WalkthroughTests.swift` into the walkthrough `scripts/` folder. That
   file is the canonical copy. Name each attachment `NN-step-slug`, with a
   zero-padded number, so the files sort in step order.

   ```swift
   import XCTest

   final class WalkthroughTests: XCTestCase {
       @MainActor
       func testWalkthrough() throws {
           let app = XCUIApplication()
           app.launchArguments = ["-SampleShell"]
           app.launch()
           XCTAssertTrue(app.windows.firstMatch.waitForExistence(timeout: 10))
           snap(app, "01-library-sample")

           app.buttons["Add Item"].click()
           XCTAssertTrue(app.sheets.firstMatch.waitForExistence(timeout: 5))
           snap(app, "02-add-item-sheet")
       }

       @MainActor
       private func snap(_ app: XCUIApplication, _ name: String) {
           let attachment = XCTAttachment(screenshot: app.screenshot())
           attachment.name = name
           attachment.lifetime = .keepAlways
           add(attachment)
       }
   }
   ```

2. In `run.sh`, copy the file into the synchronized folder of the UI test
   target. If a file with that name is already there, it belongs to the user.
   Stop, and do not overwrite it. Set `XCUI_COPY` only after the copy
   succeeds, so the cleanup never deletes a file that the run did not write:

   ```bash
   DEST="$REPO/AppUITests/WalkthroughTests.swift"
   if [[ -e "$DEST" || -L "$DEST" ]]; then
     echo "$DEST already exists. Rename the walkthrough test." >&2
     exit 1
   fi
   cp "$HERE/WalkthroughTests.swift" "$DEST"
   XCUI_COPY="$DEST"
   ```

3. Make sure that the app is not running. `app.launch()` stops a running
   instance, and a running instance belongs to the user. If one runs, stop the
   run and ask the user to quit it. Never quit or signal it yourself:

   ```bash
   SETTINGS="$(xcodebuild -scheme "$SCHEME" -destination 'platform=macOS' -showBuildSettings)"
   EXEC_NAME="$(awk -F' = ' '/ EXECUTABLE_NAME = /{print $2; exit}' <<<"$SETTINGS")"
   [[ -n "$EXEC_NAME" ]] || { echo "No EXECUTABLE_NAME for $SCHEME" >&2; exit 1; }
   EXEC_RE="$(sed 's/[][\.*^$+?(){}|]/\\&/g' <<<"$EXEC_NAME")"   # pgrep -f takes a regex
   if pgrep -f "/Contents/MacOS/${EXEC_RE}( |\$)" >/dev/null; then
     echo "$EXEC_NAME is already running. Quit it, then run again." >&2
     exit 1
   fi
   BUNDLE_ID="$(awk -F' = ' '/ PRODUCT_BUNDLE_IDENTIFIER = /{print $2; exit}' <<<"$SETTINGS")"
   [[ -n "$BUNDLE_ID" ]] || { echo "No PRODUCT_BUNDLE_IDENTIFIER for $SCHEME" >&2; exit 1; }
   # Also a copy of the app at another path. osascript fails when no app has the id.
   RUNNING="$(osascript -e "application id \"$BUNDLE_ID\" is running" 2>/dev/null)" || RUNNING=false
   if [[ "$RUNNING" == true ]]; then
     echo "$BUNDLE_ID is already running. Quit it, then run again." >&2
     exit 1
   fi
   ```

4. Build first, so the focus time covers only the test:

   ```bash
   xcodebuild build-for-testing -scheme "$SCHEME" -destination 'platform=macOS'
   ```

5. Run only the walkthrough test. The result bundle goes into `media/raw/`.
   Remove an old bundle first, because `xcodebuild` fails when the bundle path
   already exists:

   ```bash
   XCRESULT="$RAW/walkthrough.xcresult"
   rm -rf "$XCRESULT"
   xcodebuild test-without-building -scheme "$SCHEME" -destination 'platform=macOS' \
     -only-testing:"$UI_TEST_TARGET/WalkthroughTests" -resultBundlePath "$XCRESULT"
   ```

6. Extract the screenshots into `media/`, then remove the bundle:

   ```bash
   "${CLAUDE_SKILL_DIR}/scripts/xcresult_extract.py" "$XCRESULT" --out-dir "$MEDIA"
   rm -rf "$XCRESULT"
   ```

   The script prints one path per line. It strips the suffix that Xcode adds to
   each attachment name and makes the name safe for a file system. If a name
   still looks wrong, rename the file by hand.

## Launch with a project script

Read the project's agent instructions (`CLAUDE.md`, `AGENTS.md`) and its task
runner first. If they name a script or recipe that runs the macOS app, use it
in place of steps 1 and 3 of "Stills without a UI test". Such a script
usually builds the app, installs it to a fixed path, and launches it in the
background. It can also hold a lease on one shared dev app, and quit or
replace a running copy of that app. Name that behavior in the scene plan.
Never launch the build from DerivedData when the project forbids it.

1. Set `APP_PATH` to the path that the script installs to. Before you call
   the script, make sure that the app is not running, as step 2 of "Stills
   without a UI test" explains. A running copy belongs to the user:

   ```bash
   APP_PATH="/INSTALL/PATH/Example Dev.app"   # Replace with the install path of the project script
   APP_RE="$(sed 's/[][\.*^$+?(){}|]/\\&/g' <<<"$APP_PATH")"   # pgrep -f takes a regex
   if pgrep -f "^$APP_RE/Contents/MacOS/" >/dev/null; then
     echo "$APP_PATH is already running. Quit it, then run again." >&2
     exit 1
   fi
   BUNDLE_ID="com.example.dev"   # Replace with the bundle id of the app that the script installs
   if [[ -f "$APP_PATH/Contents/Info.plist" ]]; then
     BUNDLE_ID="$(plutil -extract CFBundleIdentifier raw "$APP_PATH/Contents/Info.plist")" || exit 1
   fi
   # Also a copy of the app at another path. osascript fails when no app has the id.
   RUNNING="$(osascript -e "application id \"$BUNDLE_ID\" is running" 2>/dev/null)" || RUNNING=false
   if [[ "$RUNNING" == true ]]; then
     echo "$BUNDLE_ID is already running. Quit it, then run again." >&2
     exit 1
   fi
   ```

2. Run the launch command, then set `MAC_LAUNCHED`. The `run.sh` cleanup
   runs the project's matching quit or release command, and only when this
   run launched the app. Wait for the PID of the app, with a limit:

   ```bash
   # Replace with the project's launch command.
   (cd "$REPO" && PROJECT_LAUNCH_COMMAND -SampleShell) || exit 1
   MAC_LAUNCHED=1
   APP_PID=""
   for _ in $(seq 1 40); do
     APP_PID="$(pgrep -n -f "^$APP_RE/Contents/MacOS/")" && break
     sleep 0.5
   done
   [[ -n "$APP_PID" ]] || { echo "$APP_PATH did not start" >&2; exit 1; }
   APP_NAME="$(plutil -extract CFBundleName raw "$APP_PATH/Contents/Info.plist")" || exit 1
   ```

   Do not add `APP_PID` to `PIDS`, because the project's quit command stops
   the app. After the last macOS scene, run the quit command and set
   `MAC_LAUNCHED` to empty.

3. Do steps 5 to 8 of "Stills without a UI test".

## Stills without a UI test

`screencapture -l` captures one window's own content, also when the window is
in the background, off screen, or under another window. It needs no cursor.
Use it for every still that no UI test takes.

`screencapture -l` needs Screen Recording permission. Without it, the still
can show no window content, and no error shows. Run the preflight with
`--screen` before you use this path:

```bash
"${CLAUDE_SKILL_DIR}/scripts/preflight.py" macos --screen
```

1. Build the app. Set `APP_PATH` to the build product, `EXEC_NAME` and
   `EXEC_RE` to its executable name, and `APP_NAME` to its display name:

   ```bash
   xcodebuild -scheme "$SCHEME" -destination 'platform=macOS' build || return 1
   SETTINGS="$(xcodebuild -scheme "$SCHEME" -destination 'platform=macOS' -showBuildSettings)" || return 1
   BUILT="$(awk -F' = ' '/ BUILT_PRODUCTS_DIR = /{print $2; exit}' <<<"$SETTINGS")"
   WRAPPER="$(awk -F' = ' '/ WRAPPER_NAME = /{print $2; exit}' <<<"$SETTINGS")"
   APP_PATH="$BUILT/$WRAPPER"
   EXEC_NAME="$(awk -F' = ' '/ EXECUTABLE_NAME = /{print $2; exit}' <<<"$SETTINGS")"
   [[ -n "$EXEC_NAME" ]] || { echo "No EXECUTABLE_NAME for $SCHEME" >&2; return 1; }
   EXEC_RE="$(sed 's/[][\.*^$+?(){}|]/\\&/g' <<<"$EXEC_NAME")"   # pgrep -f takes a regex
   PLIST="$APP_PATH/Contents/Info.plist"
   APP_NAME="$(plutil -extract CFBundleName raw "$PLIST" 2>/dev/null ||
     plutil -extract CFBundleExecutable raw "$PLIST")" || return 1
   ```

   `window_bounds.py` matches the window owner, which is the display name of
   the app, not the executable name. `CFBundleName` is that name for most
   apps. If the app also sets `CFBundleDisplayName`, the owner can carry that
   name. When the script finds no window, it lists the owner names that it saw
   on stderr.

   Do not use `open -a "$APP_NAME"`. It opens whichever installed app has that
   name.

2. Make sure that the app is not running. A running instance belongs to the
   user, and `open` brings it forward instead of the build that you test. If
   one runs, stop the run and ask the user to quit it. Never quit or signal it
   yourself:

   ```bash
   if pgrep -f "/Contents/MacOS/${EXEC_RE}( |\$)" >/dev/null; then
     echo "$EXEC_NAME is already running. Quit it, then run again." >&2
     return 1
   fi
   BUNDLE_ID="$(plutil -extract CFBundleIdentifier raw "$APP_PATH/Contents/Info.plist")" || return 1
   # Also a copy of the app at another path. osascript fails when no app has the id.
   RUNNING="$(osascript -e "application id \"$BUNDLE_ID\" is running" 2>/dev/null)" || RUNNING=false
   if [[ "$RUNNING" == true ]]; then
     echo "$BUNDLE_ID is already running. Quit it, then run again." >&2
     return 1
   fi
   ```

   The `pgrep` match is on the executable path, because `pgrep -x` compares
   only the first 16 characters of a process name. The bundle id check also
   finds a copy of the app that the user installed at another path.

3. Open the build in the background with the launch flags:

   ```bash
   open -g "$APP_PATH" --args -SampleShell
   ```

4. Wait for the PID of the instance that the script launched, with a limit.
   Add it to `PIDS`, so the cleanup quits it. Step 2 makes sure that no other
   instance ran before the launch, so `pgrep -n` finds only this one:

   ```bash
   APP_PID=""
   for _ in $(seq 1 40); do
     APP_PID="$(pgrep -n -f "/Contents/MacOS/${EXEC_RE}( |\$)")" && break
     sleep 0.5
   done
   [[ -n "$APP_PID" ]] || { echo "$EXEC_NAME did not start" >&2; return 1; }
   PIDS+=("$APP_PID")
   ```

5. Wait for the window of that PID, with a limit, and read the window id.
   `--pid` makes sure that the window belongs to the instance that the run
   launched, and not to a copy of the app with the same name:

   ```bash
   WIN=""
   for _ in $(seq 1 40); do
     WIN="$("${CLAUDE_SKILL_DIR}/scripts/window_bounds.py" "$APP_NAME" --pid "$APP_PID" --json 2>/dev/null)" && break
     sleep 0.5
   done
   if [[ -z "$WIN" ]]; then
     "${CLAUDE_SKILL_DIR}/scripts/window_bounds.py" "$APP_NAME" --pid "$APP_PID" >/dev/null || true   # lists the owners seen
     echo "No window for $APP_NAME" >&2
     return 1
   fi
   WINDOW_ID="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])' <<<"$WIN")"
   ```

   The JSON holds `id`, `pid`, `x`, `y`, `w`, `h`, and `on_screen`. The size
   is in points. The script also finds a window that is off screen, hidden by
   Stage Manager or on another Space, and `screencapture -l` captures that
   window at full size. `on_screen` is `false` for such a window. The
   `return 1` lines expect a capture function, as in the `run.sh` skeleton.

6. Capture the window:

   ```bash
   screencapture -x -o -l "$WINDOW_ID" "$MEDIA/04-preferences-macos.png"
   ```

7. Compare the pixel size of the PNG with the window size from step 5:

   ```bash
   sips -g pixelWidth -g pixelHeight "$MEDIA/04-preferences-macos.png"
   ```

   The pixel width must be equal to or more than `w`. On a Retina display it is
   twice `w`.

8. If the PNG is smaller than the window, Stage Manager gave you a thumbnail of
   the window. Bring the build to the front with `open "$APP_PATH"`, and do
   steps 5 to 7 one more time. The focus notice before the run already names
   this possible step, because `run.sh` cannot stop to tell the user. If the
   second capture is also small, put the still under "Not shown".

If `window_bounds.py` finds no window, the app has no open window that is at
least 100 points on each side. The script lists the app names that it saw on
stderr. Open a document or window, or bring the build to the front once, as in
step 8.

For a state that needs clicks or typing, reach the state with Peekaboo (only
with a yes), then do steps 5 to 7. A menu or popover that opens from a button
is a separate window, so `screencapture -l` of the app window leaves it out.
For a still with a menu open, capture the rectangle of the app window. `-R`
records the screen at those coordinates, so read the bounds right before the
capture with `--on-screen`. The script exits `1` when the window is off
screen, and the capture never records what the user has there:

```bash
RECT="$("${CLAUDE_SKILL_DIR}/scripts/window_bounds.py" "$APP_NAME" --pid "$APP_PID" --on-screen)" || return 1
screencapture -x -R"$RECT" "$MEDIA/02-sort-01-menu-macos.png"
```

## Video on request

Region video records part of the real screen. In the focus notice before the
run, tell the user that it records that region, and that the window must stay
uncovered for the clip. Keep each clip short.

1. Make sure that Screen Recording permission is in place. Without it, the
   video is black and no error shows. `--video` also covers the check that
   `--screen` does for stills:

   ```bash
   "${CLAUDE_SKILL_DIR}/scripts/preflight.py" macos --video
   ```

2. Start the UI test or the Peekaboo run in the background, and add its PID to
   `PIDS`. Before a UI test, do these steps of "Stills with XCUITest":

   - Steps 2 and 3. Step 2 copies the test into the target and sets
     `XCUI_COPY`, so the cleanup removes the copy. Step 3 makes sure that the
     test does not stop the user's instance of the app.
   - Step 4, the build. Then set `APP_PATH`, `EXEC_RE`, and `APP_NAME` with
     the lines of step 1 of "Stills without a UI test", without its
     `xcodebuild ... build` line.

   For a Peekaboo run, launch the app with steps 1 to 4 of "Stills without a
   UI test", or with steps 1 and 2 of "Launch with a project script". Both
   set `APP_PID`.

   Start a UI test in the background, then wait for the PID of the app that
   the test launches. The test quits that app, so do not add it to `PIDS`:

   ```bash
   XCRESULT="$RAW/walkthrough.xcresult"
   rm -rf "$XCRESULT"
   xcodebuild test-without-building -scheme "$SCHEME" -destination 'platform=macOS' \
     -only-testing:"$UI_TEST_TARGET/WalkthroughTests" -resultBundlePath "$XCRESULT" &
   DRIVER=$!
   PIDS+=("$DRIVER")
   APP_PID=""
   for _ in $(seq 1 120); do
     APP_PID="$(pgrep -n -f "/Contents/MacOS/${EXEC_RE}( |\$)")" && break
     sleep 0.5
   done
   [[ -n "$APP_PID" ]] || { echo "The UI test did not start the app" >&2; return 1; }
   ```

3. Wait for the window of `APP_PID`, with a limit. Region video records the
   screen, so read the bounds with `--on-screen`. If the window is off
   screen, bring the app to the front with `open "$APP_PATH"`, and read the
   bounds again. Then record the region with a time limit:

   ```bash
   WB="${CLAUDE_SKILL_DIR}/scripts/window_bounds.py"
   FOUND=""
   for _ in $(seq 1 120); do
     "$WB" "$APP_NAME" --pid "$APP_PID" >/dev/null 2>&1 && { FOUND=1; break; }
     sleep 0.5
   done
   [[ -n "$FOUND" ]] || { echo "No window for $APP_NAME" >&2; return 1; }
   if ! BOUNDS="$("$WB" "$APP_NAME" --pid "$APP_PID" --on-screen)"; then
     open "$APP_PATH"   # brings the running instance forward, named in the focus notice
     sleep 1
     BOUNDS="$("$WB" "$APP_NAME" --pid "$APP_PID" --on-screen)" || return 1
   fi
   screencapture -v -V 12 -k -x -R"$BOUNDS" "$RAW/05-drag-reorder-macos.mov"
   wait "$DRIVER" || true
   forget_pid "$DRIVER"
   ```

   `window_bounds.py` prints `x,y,w,h` in points, which is the format `-R`
   takes. `-k` shows clicks, and `-V` stops the recording after that many
   seconds. `forget_pid` comes from the `run.sh` skeleton. For a Peekaboo
   run, there is no `DRIVER`. Drive the app with Peekaboo while the
   recording runs, and leave out the two `DRIVER` lines.

4. Let the encode step in `run.sh` turn the `.mov` into an MP4 and a poster.

## Peekaboo

Use Peekaboo only with the user's yes for this run. Peekaboo clicks and types
in the real app, so the user must not use the app while it runs. If the app
window is on screen, Peekaboo clicks in the background and leaves the cursor
and the focus alone. If the window is off screen, hidden by Stage Manager or
on another Space, Peekaboo cannot read or click it. The app must then come to
the front, which takes focus. Name that step in the focus notice.

Peekaboo needs two permissions for your terminal: Accessibility and Screen
Recording. Run `peekaboo permissions status` to see whether both are in place.
If one is missing, name its pane in **System Settings > Privacy & Security**,
as for any other missing permission. The stills that follow a Peekaboo run
come from `screencapture`, so run the preflight with `--screen` too.

The CLI changes between versions, so read `peekaboo --help` first. These steps
use Peekaboo 4.8. Target the app by the PID of the instance that the run
launched (`APP_PID`):

1. List the windows of the app. The JSON gives each window its `window_id`,
   its `bounds`, and `is_on_screen`, and it includes windows that are off
   screen:

   ```bash
   peekaboo window list --pid "$APP_PID" --json
   ```

2. If the window is off screen, bring the running instance to the front with
   `open "$APP_PATH"`. Do not add `-n`, because `-n` opens a second instance.
   `peekaboo window focus` fails for a window that is off screen.
3. Take a snapshot with `peekaboo see --pid "$APP_PID" --json`. The output
   holds a snapshot id and an id for each element. Find the element by its
   accessibility label, for example a button "Sort by Title, A to Z", a menu
   item "Title", or a sidebar row "Recordings".
4. Click the element with the ids from that snapshot:

   ```bash
   peekaboo click --on "$ELEMENT_ID" --snapshot "$SNAPSHOT_ID" --pid "$APP_PID"
   ```

5. Take a new snapshot after each click, because element ids belong to one
   snapshot.

This helper does steps 3 to 5 for one label:

```bash
pk_click() {
  local label=$1 out snap id
  out="$(peekaboo see --pid "$APP_PID" --json)" || return 1
  read -r snap id < <(python3 -c '
import json, sys
d = json.load(sys.stdin)["data"]
ids = [e["id"] for e in d.get("ui_elements", []) if (e.get("label") or e.get("title")) == sys.argv[1]]
print(d["snapshot_id"], ids[0] if ids else "")' "$label" <<<"$out") || return 1
  [[ -n "$id" ]] || { echo "No element labeled '$label'" >&2; return 1; }
  peekaboo click --on "$id" --snapshot "$snap" --pid "$APP_PID" >/dev/null || return 1
  sleep 0.8   # let the click take effect before the next snapshot
}
```

Use Peekaboo only to reach the state. Take the still with `screencapture -l`,
or with `screencapture -R` when a menu is open, as "Stills without a UI test"
shows.
