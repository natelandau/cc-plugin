# iOS captures

This file tells you how to capture stills and clips of an iOS app in a
simulator. The simulator runs without a window, so the user keeps their screen.

`${CLAUDE_SKILL_DIR}` in the commands below is not an environment variable.
Replace it with the absolute skill directory that SKILL.md shows.

## Rules

- Read the project's agent instructions (`CLAUDE.md`, `AGENTS.md`) and its
  task runner first. Use the project's own recipes for the build, the
  simulator, the install, seed data, and test accounts. The commands below are
  the fallback.
- Boot the simulator with `xcrun simctl boot`. Never open Simulator.app, and
  never open DeviceHub, which hosts the simulators in Xcode versions that have
  no Simulator.app. `simctl io` and Maestro work with a device that has no
  window.
- Before you boot a device, record whether it was already booted. Reuse a
  booted device. Shut down only a device that this run booted.
- The run installs the app on a simulator that the user already has, booted
  or shut down. The install replaces any build of the app on that simulator,
  so name the simulator in the scene plan before the run.
- On a reused device, never stop or reset an app that the user has open.
  The install and every driver stop a running copy of the app, so step 3 of
  "Pick and boot a device" comes before them.
- Override the status bar for the run, and clear the override on exit.
- Choose the driver in the order of "Choose the driver" below.
- Start the app in a known state with launch arguments. Never use the user's
  real data or account.

## Pick and boot a device

1. List the devices and pick an iPhone with a runtime that the project
   supports:

   ```bash
   xcrun simctl list devices available
   ```

2. Find out whether that device is already booted. Boot it and wait only if it
   is not:

   ```bash
   BOOTED_LIST="$(xcrun simctl list devices booted)"
   if grep -qF "$UDID" <<<"$BOOTED_LIST"; then
     echo "reuse booted $UDID"
   else
     xcrun simctl boot "$UDID"
     BOOTED_UDID="$UDID"   # cleanup shuts down only this one
     xcrun simctl bootstatus "$UDID"
   fi
   ```

   Keep the list in a variable before `grep -q`. With `set -o pipefail`, a
   pipe into `grep -q` can report a failure when `grep` exits early.

3. If the run reused the device (`BOOTED_UDID` is empty), make sure that the
   app is not running on it. Do this before the install, because
   `simctl install` stops a running copy of the app. A running app belongs to
   the user. Maestro `launchApp`, XCUITest `app.launch()`, and `simctl launch
   --terminate-running-process` also stop it. If it runs, stop the run and ask
   the user to quit it. Never stop it yourself:

   ```bash
   if [[ -z "$BOOTED_UDID" ]]; then
     LAUNCHD="$(xcrun simctl spawn "$UDID" launchctl list)" ||
       { echo "Cannot list the processes on $UDID" >&2; exit 1; }
     if grep -qF "UIKitApplication:$BUNDLE_ID[" <<<"$LAUNCHD"; then
       echo "$BUNDLE_ID is running on $UDID. Quit it, then run again." >&2
       exit 1
     fi
   fi
   ```

   Get `BUNDLE_ID` from `PRODUCT_BUNDLE_IDENTIFIER` in
   `xcodebuild -scheme "$SCHEME" -destination "id=$UDID" -showBuildSettings`.
   After this step, the app runs only when this run launched it.

4. Set the status bar, unless the user already set an override. The output of
   `xcrun simctl status_bar "$UDID" list` always starts with two header lines.
   An override exists only when more lines follow. Keep the user's override:

   ```bash
   SB_LIST="$(xcrun simctl status_bar "$UDID" list)" || exit 1
   if (($(wc -l <<<"$SB_LIST") > 2)); then
     echo "Keep the status-bar override that is already on $UDID"
   else
     xcrun simctl status_bar "$UDID" override --time 9:41 --batteryState charged \
       --batteryLevel 100 --cellularBars 4 --wifiBars 3
     STATUS_BAR_UDID="$UDID"   # cleanup runs: xcrun simctl status_bar "$UDID" clear
   fi
   ```

5. Build the app for that simulator, and install it:

   ```bash
   xcodebuild -scheme "$SCHEME" -destination "id=$UDID" build
   xcrun simctl install "$UDID" "$APP_PATH"
   ```

   Get `APP_PATH` from `BUILT_PRODUCTS_DIR` and `WRAPPER_NAME` in
   `xcodebuild -scheme "$SCHEME" -destination "id=$UDID" -showBuildSettings`.
   Keep the default DerivedData location, so the build reuses the user's cache.

6. After the first capture, make sure that the still is portrait: its pixel
   height is more than its width, and the UI shows the expected layout. A
   device booted with no window can start in landscape, and Maestro
   `setOrientation` does not rotate it. If the still is landscape, shut down
   the device only if this run booted it. Pick another iPhone model, and tell
   the user its name, because the install replaces the app on it. Wait for
   the user's yes, as for the scene plan. Then set `UDID` to that device and
   run again:

   ```bash
   sips -g pixelWidth -g pixelHeight "$MEDIA/01-list-sample-ios.png"
   ```

## Choose the driver

Use the first driver in this list that works:

1. Maestro. This is the default.
2. XCUITest, if Maestro fails and the project has a synchronized UI test
   target. A synchronized UI test target is a UI test target
   (`com.apple.product-type.bundle.ui-testing`) with an Xcode 16 synchronized
   folder (`PBXFileSystemSynchronizedRootGroup`) in `project.pbxproj`.
3. `xcrun simctl launch` with launch flags, and stills from `simctl io`, if the
   project has no synchronized UI test target. This driver cannot tap, so put
   the scenes that need input under "Not shown". Launch the app once for each
   launch state, then take the still:

   ```bash
   xcrun simctl launch --terminate-running-process "$UDID" "$BUNDLE_ID" -SampleShell
   sleep 3   # simctl cannot wait for an element
   xcrun simctl io "$UDID" screenshot "$MEDIA/01-list-sample-ios.png"
   ```

   `--terminate-running-process` is safe here, because step 3 of "Pick and
   boot a device" makes sure that any running copy is one that this run
   launched. It restarts the app for the next launch state.

Never open Simulator.app or DeviceHub to make a driver work. Never add a UI
test target, and never edit `project.pbxproj`. Record the driver that you
used, and the reason for each change of driver, in the capture log.

## Find the launch state

Search the app for DEBUG launch flags that start it in a sample state, such as
`-SampleShell`. Look for `ProcessInfo.processInfo.arguments`, `UserDefaults`
keys read at launch, and `#if DEBUG` blocks. If no flag reaches the starting
state of a scene, put that scene under "Not shown" with the reason.

The run never clears the app data, so the flag must keep its sample data in a
store apart from the user's data. Each scene starts with the data that the
earlier scenes left. Order the scenes to match, or reset the sample data with
the app's own sample flag. If the flag writes into the normal store, ask the
user before you use it.

## Drive with Maestro

Write one flow per scene into `scripts/`. `takeScreenshot` and
`startRecording` take a path without an extension. Maestro adds `.png` or
`.mp4`.

Maestro sends anonymous analytics and prints a notice on each run by default.
The `run.sh` skeleton turns both off with this line near the top:

```bash
export MAESTRO_CLI_NO_ANALYTICS=1 MAESTRO_CLI_ANALYSIS_NOTIFICATION_DISABLED=true
```

```yaml
# scripts/ios-03-add-item.yaml
appId: com.example.groceries
---
- launchApp:
    arguments:
      -SampleShell: true
- extendedWaitUntil:
    visible: "Groceries"
    timeout: 10000
- takeScreenshot: 03-add-item-01-list-ios
- startRecording: 03-add-item-ios
- tapOn: "Add item"
- inputText: "Buy oat milk"
- tapOn: "Save"
- assertVisible: "Buy oat milk"
- stopRecording
```

```bash
maestro --device "$UDID" test --test-output-dir "$RAW/maestro" ios-03-add-item.yaml
```

After the run, move only the files that the flow names. Maestro also writes
its own screenshots when a step fails, and those do not belong in `media/`:

```bash
move_named() {
  local name=$1 dest=$2 found
  found="$(find "$RAW/maestro" "$HERE" -name "$name" | head -n 1)"
  if [[ -z "$found" ]]; then
    echo "Maestro wrote no $name" >&2
    return 1
  fi
  mv "$found" "$dest/"
}
move_named 03-add-item-01-list-ios.png "$MEDIA" &&
  move_named 03-add-item-ios.mp4 "$RAW"
```

Maestro can write a `takeScreenshot` file into the test output directory or
into the folder of the flow, so the function searches both.

Do not set `clearState: true` in `launchApp`. It erases the app data that
the user keeps in that simulator. Reach the starting state with launch
arguments.

Maestro passes each `arguments:` key to the app as a launch argument. Write
the key with the dash, as the flow above shows. An app that checks
`CommandLine.arguments.contains("-SampleShell")` needs the key `-SampleShell`.
If the first still does not show the sample state, compare the key with the
check in the app.

If Maestro fails to connect to the device, go to the next driver in "Choose
the driver".

## Drive with XCUITest

Use XCUITest only through "Choose the driver", and only with a synchronized
UI test target.

1. Write `WalkthroughTests.swift` into the walkthrough `scripts/` folder. That
   file is the canonical copy.
2. In `run.sh`, copy it into the synchronized folder of the UI test target.
   If a file with that name is already there, it belongs to the user. Stop,
   and do not overwrite it. Set `XCUI_COPY` only after the copy succeeds, so
   the cleanup never deletes a file that the run did not write:

   ```bash
   DEST="$REPO/AppUITests/WalkthroughTests.swift"
   if [[ -e "$DEST" || -L "$DEST" ]]; then
     echo "$DEST already exists. Rename the walkthrough test." >&2
     exit 1
   fi
   cp "$HERE/WalkthroughTests.swift" "$DEST"
   XCUI_COPY="$DEST"
   ```

3. Set `app.launchArguments` for the launch state:

   ```swift
   let app = XCUIApplication()
   app.launchArguments = ["-SampleShell"]
   app.launch()
   ```

`xcodebuild test` can open the Simulator window and take focus. Name this
step in the focus notice that you give before `run.sh` starts, because
`run.sh` cannot pause to warn the user in the middle of a run.

Run only the walkthrough test. The result bundle goes into `media/raw/`.
Remove an old bundle first, because `xcodebuild` fails when the bundle path
already exists:

```bash
XCRESULT="$RAW/walkthrough.xcresult"
rm -rf "$XCRESULT"
xcodebuild test -scheme "$SCHEME" -destination "id=$UDID" \
  -only-testing:"$UI_TEST_TARGET/WalkthroughTests" -resultBundlePath "$XCRESULT"
```

Take stills in one of two ways:

- In the test, add an `XCTAttachment(screenshot: app.screenshot())` with
  `lifetime = .keepAlways` and `name` set to `NN-step-slug`. Extract them
  after the run, then remove the bundle:

  ```bash
  "${CLAUDE_SKILL_DIR}/scripts/xcresult_extract.py" "$XCRESULT" --out-dir "$MEDIA"
  rm -rf "$XCRESULT"
  ```

  The script strips the suffix that Xcode adds to each name. If a name still
  looks wrong, rename the file by hand.

- From outside the test, with `simctl`:

  ```bash
  xcrun simctl io "$UDID" screenshot "$MEDIA/03-add-item-01-list-ios.png"
  ```

## Record a clip with simctl

`recordVideo` runs until it gets SIGINT. Start it in the background, wait for
`Recording started` on its stderr, drive the app, then stop it. The wait has a
limit, and it stops early if the recorder exits. After `wait`, remove the PID
from `PIDS` with `forget_pid` from the `run.sh` skeleton, so the cleanup never
signals a reused PID. The `return 1` line expects a capture function, as in
the `run.sh` skeleton.

```bash
xcrun simctl io "$UDID" recordVideo --codec=h264 --force "$RAW/03-add-item-ios.mp4" \
  2>"$RAW/rec.log" &
REC=$!
PIDS+=("$REC")
for _ in $(seq 1 50); do
  grep -q "Recording started" "$RAW/rec.log" && break
  kill -0 "$REC" 2>/dev/null || break
  sleep 0.2
done
grep -q "Recording started" "$RAW/rec.log" || { echo "recordVideo did not start" >&2; return 1; }
# ... drive the app here ...
kill -INT "$REC"
wait "$REC" || true   # simctl finalizes the file before it exits
forget_pid "$REC"
```

Use `--codec=h264`. The default codec is HEVC.

## Gotchas

- `simctl` cannot tap or type. Use it only to capture.
- If `xcodebuild test` opens Simulator.app, record it in the capture log.
- Several devices can be booted at once. Always pass the UDID to `simctl`,
  `xcodebuild`, and `maestro`.
