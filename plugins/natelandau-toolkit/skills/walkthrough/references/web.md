# Web captures

This file tells you how to capture stills and clips of a web UI with
`shot-scraper`. Every browser runs headless, so the user keeps their screen.

## Rules

- Run headless only. Never use `--interactive`, a headed browser, or a
  Playwright `headless: false` option.
- Put each viewport in its own shot. The defaults are desktop `1440x900` and
  mobile `390x844`.
- Wait for an element, not for a fixed time. A fixed `wait` is a last resort.
- Menus, sheets, and popovers animate after they become visible. Before a
  still with one open, wait until its last item stops moving. In Playwright,
  use the e2e suite's settle helper, or `waitSettled` in "Playwright instead".
  In a `shot-scraper` storyboard, add a `pause` of about 0.5 seconds after the
  `wait_for`.
- Write raw clips to `../media/raw/`. The final `run.sh` step encodes them with
  `encode.py`, so never pass `--mp4` to `shot-scraper video`.
- Write the YAML files into the walkthrough `scripts/` folder and run them from
  that folder. Output paths are relative to the current directory.

## Start the dev server

Read the project's agent instructions (`CLAUDE.md`, `AGENTS.md`) and its task
runner first. Use the project's own recipes for the dev server, seed data, and
test accounts. The commands below are the fallback.

Use the project's own dev-server command and a port that nothing else uses. If
the usual port already has a listener, the user runs a server there. Pick a
different port and do not touch that server.

The `server:` key starts a server for one `shot-scraper` run, waits up to 30
seconds for its port, and kills it at the end. It kills only the process that
it started. Use `server:` only when the command is the server process itself,
in list form:

```yaml
server: ["python3", "-m", "http.server", "8765"]
```

If the command is a wrapper that starts child processes (`npm run dev`, `pnpm
dev`, `just serve`, `make`), the kill leaves the real server running. In that
case, start the server in `run.sh`, wait for it, and stop its process tree on
exit. If the first build takes more than 30 seconds, do the same.

## Stills: `shot-scraper multi`

Write one entry per step and viewport. If the entry has a `height`, the shot
is the viewport only. If it has no `height`, the shot is the full page.

```yaml
# scripts/shots.yml
- url: http://localhost:5199/settings
  output: ../media/01-settings-desktop.png
  width: 1440
  height: 900
  wait_for: document.querySelector('[data-testid="settings-form"]')
- url: http://localhost:5199/settings
  output: ../media/01-settings-mobile.png
  width: 390
  height: 844
  wait_for: document.querySelector('[data-testid="settings-form"]')
```

```bash
shot-scraper multi shots.yml
```

In `multi`, `wait_for` is a JavaScript expression that must become truthy. A
CSS selector there does not work. Wrap it in `document.querySelector(...)`.
`wait` is in milliseconds.

To reach a state that needs clicks, add `javascript:` to the entry, or record
the steps as a storyboard and use its `screenshot:` action.

## Clips: `shot-scraper video`

Use a storyboard for a behavior that is motion or a sequence. Turn on the cursor
and the click rings, so the user can see each action.

```yaml
# scripts/03-add-item.yml
output: ../media/raw/03-add-item-desktop.webm
url: http://localhost:5199/items
viewport:
  width: 1440
  height: 900
cursor:
  visible: true
  clicks: true
wait_for: "[data-testid='item-list']"
scenes:
  - name: Open the add dialog
    do:
      - click: "button:has-text('Add item')"
      - wait_for: "role=dialog"
      - pause: 0.5
  - name: Save the item
    do:
      - type:
          into: "input[name='title']"
          text: "Buy oat milk"
          delay_ms: 30
      - click: "button:has-text('Save')"
      - wait_for: "text=Buy oat milk"
      - pause: 1
```

```bash
shot-scraper video 03-add-item.yml
```

In a storyboard, `wait_for` is a selector or a Playwright text selector, not
JavaScript. `pause` and the top-level `wait` are in seconds. The output is
WebM. End each clip on the result, because the poster is the final frame.

A storyboard also accepts a `screenshot:` action inside `do:`, which gives you
a still from the same run:

```yaml
      - screenshot: ../media/03-add-item-02-saved-desktop.png
```

Make one storyboard per viewport. A storyboard has one `viewport`.

## Playwright instead

If the project already depends on Playwright, you can write a short script that
uses the project's install. Do not install Playwright into a project that does
not have it. Set `recordVideo` on the context. Playwright writes the video when
the context closes.

```js
// scripts/03-add-item.mjs. Run it from scripts/: node 03-add-item.mjs
import { chromium } from "@playwright/test";

const browser = await chromium.launch(); // headless by default
const context = await browser.newContext({
  viewport: { width: 1440, height: 900 },
  recordVideo: { dir: "../media/raw", size: { width: 1440, height: 900 } },
});
const page = await context.newPage();
await page.goto("http://localhost:5199/items");
await page.getByRole("button", { name: "Add item" }).click();
await page.getByRole("dialog").waitFor();
await page.screenshot({ path: "../media/03-add-item-01-dialog-desktop.png" });
const video = page.video();
await context.close(); // finalizes the video
await video.saveAs("../media/raw/03-add-item-desktop.webm");
await video.delete(); // saveAs copies, so remove the randomly named original
await browser.close();
```

Playwright gives the video a random name. `saveAs` writes a copy with the
scene name, and `delete` removes the original. Without `delete`, the encode
step also encodes the original as a stray clip.

This helper waits until an animated menu or sheet stops moving. It compares
the bounding box of an element in two reads 100 ms apart:

```js
async function waitSettled(locator) {
  let last = "";
  for (let i = 0; i < 40; i++) {
    const box = JSON.stringify(await locator.boundingBox());
    if (box !== "null" && box === last) return;
    last = box;
    await locator.page().waitForTimeout(100);
  }
  throw new Error("The element did not stop moving");
}

await waitSettled(page.getByRole("menuitem").last());
```

## Signed-in apps

`shot-scraper` cannot sign in. If a scene needs a signed-in user, and the
project has a Playwright e2e suite with sign-in helpers, capture through that
suite. The suite's e2e command owns the test server, the test-mode users, and
a throwaway database.

1. Write the capture spec into the walkthrough `scripts/` folder. That file is
   the canonical copy. Import the suite's own helpers for sign-in, seed data,
   and waits.
2. Read the media folder from the `WALKTHROUGH_MEDIA` environment variable,
   and write every still and raw clip below it. For a clip, open a new
   context from the `browser` fixture with `recordVideo` set, because the
   `page` fixture of the test runner does not record by default. Then use
   `saveAs` and `delete` as "Playwright instead" shows.

   ```ts
   import { expect, test } from "@playwright/test";
   import { signInAs } from "./helpers"; // the suite's own helpers

   const MEDIA = process.env.WALKTHROUGH_MEDIA ?? "";

   test("walkthrough captures", async ({ page }) => {
     expect(MEDIA, "WALKTHROUGH_MEDIA must name the media folder").not.toBe("");
     await page.setViewportSize({ width: 390, height: 844 });
     await signInAs(page, "e2e-user@example.com");
     await page.goto("/settings");
     await expect(page.getByTestId("settings-form")).toBeVisible();
     await page.screenshot({ path: `${MEDIA}/01-settings-mobile.png` });
   });

   test("walkthrough clip", async ({ browser }) => {
     const context = await browser.newContext({
       viewport: { width: 1440, height: 900 },
       recordVideo: { dir: `${MEDIA}/raw`, size: { width: 1440, height: 900 } },
     });
     const desk = await context.newPage();
     await signInAs(desk, "e2e-user@example.com");
     // ... the steps of the clip ...
     const video = desk.video();
     await context.close();
     if (video) {
       await video.saveAs(`${MEDIA}/raw/03-add-item-desktop.webm`);
       await video.delete();
     }
   });
   ```

3. In `run.sh`, copy the spec into the e2e folder of the project. If a file
   with that name is already there, it belongs to the user. Stop the step, and
   do not overwrite it. Set `E2E_SPEC_COPY` only after the copy succeeds, so
   the cleanup never deletes a file that the run did not write.
4. Run the project's own e2e command for that one spec, with
   `WALKTHROUGH_MEDIA` set. If the suite has several Playwright projects or
   configs, select one, for example with `--project`. Each project runs the
   spec again and writes the same file names, so the outputs collide:

   ```bash
   capture_signed_in() {
     local dest="$REPO/e2e/walkthrough-capture.spec.ts"
     if [[ -e "$dest" || -L "$dest" ]]; then
       echo "$dest already exists. Rename the walkthrough spec." >&2
       return 1
     fi
     cp "$HERE/walkthrough-capture.spec.ts" "$dest" || return 1
     E2E_SPEC_COPY="$dest"
     # Replace PROJECT_E2E_COMMAND with the project's e2e command and its project option.
     (cd "$REPO" && WALKTHROUGH_MEDIA="$MEDIA" PROJECT_E2E_COMMAND walkthrough-capture.spec.ts) ||
       return 1
     rm -f "$dest"
     E2E_SPEC_COPY=""
   }
   step "signed-in captures" capture_signed_in
   ```

Use only the suite's test-mode users. Write data only into the throwaway
database that the e2e run creates. An empty account can hide the UI of a
scene, for example list headers. In that case, add a few rows with the
suite's own helpers inside the spec.

If the project has no e2e command that creates and owns its own throwaway
database, the spec must not add data. Put the scenes that need added data
under "Not shown" with the reason.

## Before and after

Show a "before" only when it is straightforward. That means the "before"
commit checks out into a temporary worktree and starts with the same command
and launch state, with no migrations, new seed data, or other setup.
Otherwise, write one sentence that describes the old behavior.

1. Find the "before" commit. It is the merge base of `HEAD` and the default
   branch. If the change is already on the default branch, because `HEAD` is
   the default branch or the change is a merged commit, the merge base
   includes the change. In that case, set `CHANGE` to the oldest commit of the
   change, and the "before" is its parent (`<sha>^`):

   ```bash
   DEFAULT="$(git -C "$REPO" symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null || true)"
   DEFAULT="${DEFAULT#origin/}"
   if [[ -z "$DEFAULT" ]]; then
     if git -C "$REPO" show-ref --verify --quiet refs/heads/main; then DEFAULT=main; else DEFAULT=master; fi
   fi
   CHANGE=""   # the oldest commit of the change, only when it is on $DEFAULT
   if [[ -n "$CHANGE" ]]; then
     BASE="$(git -C "$REPO" rev-parse "$CHANGE^")"
   else
     BASE="$(git -C "$REPO" merge-base HEAD "$DEFAULT")"
   fi
   ```

   If `HEAD` is the default branch and the change is not committed, the merge
   base is `HEAD`, which is the correct "before".

2. Add a detached worktree of that commit inside the walkthrough folder. A
   detached worktree works when a branch is checked out somewhere else. Put
   the add into a capture function, and run it with `step`, as the `run.sh`
   skeleton shows. If the add fails, the run continues, and the "before"
   captures go under "Not shown". Set `BEFORE_DIR` right after the add, so the
   `run.sh` cleanup removes the worktree:

   ```bash
   # True if git lists this exact folder as one of its worktrees.
   is_listed_worktree() {
     local want path line list
     want="$(cd "$1" && pwd -P)" || return 1
     list="$(git -C "$REPO" worktree list --porcelain)" || return 1
     while IFS= read -r line; do
       [[ "$line" == "worktree "* ]] || continue
       path="${line#worktree }"
       [[ -d "$path" && "$(cd "$path" && pwd -P)" == "$want" ]] && return 0
     done <<<"$list"
     return 1
   }

   add_before_worktree() {
     local dir="$HERE/../before-src"
     if [[ -d "$dir" && -n "$(ls -A "$dir")" ]]; then
       if is_listed_worktree "$dir"; then
         git -C "$REPO" worktree remove --force "$dir" || return 1
       else
         echo "$dir is not a worktree of this repo. Skipping before/after." >&2
         return 1
       fi
     fi
     git -C "$REPO" worktree add -f --detach "$dir" "$BASE" || return 1
     BEFORE_DIR="$dir"
   }
   ```

   A `before-src` folder that is not empty is left from an earlier run that
   did not finish. Remove it only when `git worktree list` shows that exact
   path. Otherwise, the folder can hold files that the run did not create, so
   leave it, skip the before/after, and say why under "Not shown".

   `-f` reuses the record of an earlier run whose folder is gone. Do not run
   `git worktree prune`, because it also removes the records of the user's
   worktrees on a disconnected volume.

3. Install dependencies in that worktree with the project's command.
4. Start its dev server on a second port, add its PID to `PIDS`, and wait for
   it.
5. Run the same storyboard or `multi` file with the URL changed to the second
   port and `-before` added to each output name.

Put steps 2 to 5 into one capture function, so that one `step` call runs them.
End each command with `|| return 1`. If any of them fails, the "after"
captures stay, and the "before" captures go under "Not shown" with the error:

```bash
capture_before() {
  add_before_worktree || return 1
  # ... install, start the second server, and capture, each with `|| return 1`
}
step "before captures" capture_before
```
