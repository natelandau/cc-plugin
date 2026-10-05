# Android captures

This file tells you how to capture stills and clips of an Android app in an
emulator. The emulator runs without a window, so the user keeps their screen.

## Rules

- Read the project's agent instructions (`CLAUDE.md`, `AGENTS.md`) and its
  task runner first. Use the project's own recipes for the build, the
  emulator, the install, seed data, and test accounts. The commands below are
  the fallback.
- Start an emulator with `-no-window`.
- Reuse an emulator that is already running. Stop only an emulator that this
  run started.
- The run installs the app on a virtual device that the user already has,
  running or not. The install replaces any build of the app on that device,
  so name the device in the scene plan before the run.
- On a reused emulator, never stop or reset an app that the user has open.
  The install and Maestro `launchApp` stop a running copy of the app, so step
  4 of "Pick and start an emulator" comes before them.
- Drive the app with Maestro by default.
- Start the app in a known state with launch arguments or intent extras. Never
  use the user's real data or account.

## Pick and start an emulator

1. Look for a running emulator first:

   ```bash
   adb devices
   ```

   If a line shows `emulator-NNNN  device`, set `SERIAL` to that serial, leave
   `EMULATOR_SERIAL` empty, and skip to step 4.

2. List the virtual devices, and start one on a fixed port, so you know its
   serial:

   ```bash
   emulator -list-avds
   emulator -avd "$AVD" -port 5580 -no-window -no-audio -no-boot-anim &
   EMULATOR_SERIAL="emulator-5580"   # cleanup runs: adb -s "$EMULATOR_SERIAL" emu kill
   SERIAL="$EMULATOR_SERIAL"
   ```

3. Wait for the boot to finish, with a limit of about 3 minutes:

   ```bash
   BOOTED=""
   for _ in $(seq 1 180); do
     if [ "$(adb -s "$SERIAL" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = "1" ]; then
       BOOTED=1
       break
     fi
     sleep 1
   done
   [[ -n "$BOOTED" ]] || { echo "Emulator $SERIAL did not boot" >&2; exit 1; }
   ```

4. If the run reused the emulator (`EMULATOR_SERIAL` is empty), make sure
   that the app is not running on it. Do this before the install, because the
   install stops a running copy of the app. A running app belongs to the user.
   If it runs, stop the run and ask the user to quit it. Never stop it
   yourself:

   ```bash
   if [[ -z "$EMULATOR_SERIAL" ]]; then
     PID_OUT="$(adb -s "$SERIAL" shell pidof "$APP_ID" 2>&1 | tr -d '\r')" || true
     if [[ "$PID_OUT" =~ ^[0-9\ ]+$ ]]; then
       echo "$APP_ID is running on $SERIAL. Quit it, then run again." >&2
       exit 1
     elif [[ -n "$PID_OUT" ]]; then
       echo "Cannot check $APP_ID on $SERIAL: $PID_OUT" >&2
       exit 1
     fi
   fi
   ```

   Test the output, not the exit status. Before API 24, `adb shell` always
   exits with `0`. Output that is not a PID, such as `pidof: not found`, stops
   the run, because the check cannot prove that the app is stopped. `APP_ID`
   is the `applicationId` of the debug build.

5. Install the debug build with the project's command, for example:

   ```bash
   ANDROID_SERIAL="$SERIAL" ./gradlew installDebug
   ```

## Drive with Maestro

Write one flow per scene into `scripts/`. On Android, Maestro passes
`arguments:` to the app as intent extras.

```yaml
# scripts/android-03-add-item.yaml
appId: com.example.groceries
---
- launchApp:
    arguments:
      sampleMode: "true"
- extendedWaitUntil:
    visible: "Groceries"
    timeout: 10000
- takeScreenshot: 03-add-item-01-list-android
- startRecording: 03-add-item-android
- tapOn: "Add item"
- inputText: "Buy oat milk"
- tapOn: "Save"
- assertVisible: "Buy oat milk"
- stopRecording
```

Do not set `clearState: true` in `launchApp`. It erases the app data that
the user keeps in that emulator. Reach the starting state with launch
arguments.

The sample flag must keep its sample data in a store apart from the user's
data. Each scene starts with the data that the earlier scenes left. Order the
scenes to match, or reset the sample data with the app's own sample flag. If
the flag writes into the normal store, ask the user before you use it.

```bash
maestro --device "$SERIAL" test --test-output-dir "$RAW/maestro" android-03-add-item.yaml
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
move_named 03-add-item-01-list-android.png "$MEDIA" &&
  move_named 03-add-item-android.mp4 "$RAW"
```

Maestro can write a `takeScreenshot` file into the test output directory or
into the folder of the flow, so the function searches both. The `run.sh`
skeleton turns off the Maestro analytics and the notice that Maestro prints
on each run.

## Capture with adb

Use `adb` for a still or a clip when Maestro does not drive that step.

Take a still:

```bash
adb -s "$SERIAL" exec-out screencap -p > "$MEDIA/03-add-item-01-list-android.png"
```

Record a clip. `screenrecord` stops after `--time-limit` seconds, and it cannot
record more than 3 minutes. Set `DEVICE_CLIP` and `DEVICE_CLIP_SERIAL` before
the recording starts, so the `run.sh` cleanup removes that one file if the run
stops early. `DEVICE_CLIP` holds one path only. Remove the device file before
the function returns, also when the `pull` fails, so the next clip does not
leave this one behind:

```bash
DEVICE_CLIP="/sdcard/walkthrough-$$-03-add-item.mp4"   # a name that no user file has
DEVICE_CLIP_SERIAL="$SERIAL"
adb -s "$SERIAL" shell screenrecord --time-limit 12 "$DEVICE_CLIP" &
REC=$!
PIDS+=("$REC")
# ... drive the app here ...
wait "$REC" || true
forget_pid "$REC"   # from the run.sh skeleton
PULLED=1
adb -s "$SERIAL" pull "$DEVICE_CLIP" "$RAW/03-add-item-android.mp4" || PULLED=""
adb -s "$SERIAL" shell rm -f "$DEVICE_CLIP"
DEVICE_CLIP=""
[[ -n "$PULLED" ]] || return 1
```

The `return 1` line expects a capture function, as in the `run.sh` skeleton.
Between the start of the recording and the `rm`, do not return from the
function. If a step that drives the app fails, record the failure in a
variable, as `PULLED` does, and return after the `rm`.

Use `exec-out` for `screencap`. `adb shell` changes line endings and breaks
the PNG.
