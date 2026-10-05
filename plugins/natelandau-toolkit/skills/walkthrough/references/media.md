# Media

This file tells you how to name, encode, and embed the captured media.

`${CLAUDE_SKILL_DIR}` in the commands below is not an environment variable.
Replace it with the absolute skill directory that SKILL.md shows.

## Names and folders

- Write stills straight into `media/` as PNG. Do not convert them.
- Write raw clips into `media/raw/`. The encode step writes the results into
  `media/` and deletes each raw clip after a successful encode.
- Start each name with a zero-padded number and a short slug, then add the
  variant: `03-add-item-01-dialog-desktop.png`, `03-add-item-ios.mp4`. The
  files then sort in walkthrough order.

## Encode clips

`encode.py` turns any clip that ffmpeg reads (`.webm`, `.mov`, `.mp4`) into a
silent H.264 MP4 and a poster PNG:

```bash
"${CLAUDE_SKILL_DIR}/scripts/encode.py" "$RAW/03-add-item-desktop.webm" --out-dir "$MEDIA"
```

It prints the two output paths as JSON:

```json
{"mp4": ".../media/03-add-item-desktop.mp4", "poster": ".../media/03-add-item-desktop.poster.png"}
```

| Option | Effect |
|---|---|
| `--out-dir DIR` | Required. The outputs are `DIR/<stem>.mp4` and `DIR/<stem>.poster.png`. |
| `--max-width N` | Scale wider clips down to `N` pixels. The default is `1280`. It never scales up. |
| `--start S` | Cut the clip to start at `S` seconds. |
| `--end E` | Cut the clip to end at `E` seconds. |

Exit codes: `0` success, `1` ffmpeg failed (the last ffmpeg lines go to
stderr), `2` ffmpeg is not installed.

The poster is the last frame of the clip. If the clip is too short to seek from
the end, the poster is the first frame. End each clip on the result of the
behavior, so the poster shows it.

If the source is an `.mp4`, it must be in a different folder from `--out-dir`.
Otherwise the script stops, because the output path is the source path.

## Keep clips short

Keep each clip under about 15 seconds. Use `--start` and `--end` to cut a slow
launch or an idle tail. After the encode, look at each poster. If a poster
shows a spinner, an error, or the wrong state, the clip failed the self-check.

## Embed in the page

Reference media by relative path. Do not embed base64.

A clip:

```html
<video controls muted loop playsinline preload="metadata"
       poster="media/03-add-item-desktop.poster.png">
  <source src="media/03-add-item-desktop.mp4" type="video/mp4">
</video>
```

Stills for one scene go in a row, with a caption for each step:

```html
<div class="steps">
  <figure>
    <img src="media/03-add-item-01-dialog-desktop.png" alt="Add item dialog, empty">
    <figcaption>1. Click Add item.</figcaption>
  </figure>
  <figure>
    <img src="media/03-add-item-02-saved-desktop.png" alt="List with the new item">
    <figcaption>2. Type a title and click Save.</figcaption>
  </figure>
</div>
```

## Several viewports or platforms at one step

Put the captures of one step side by side, so the user compares them at one
glance. Let a narrow mobile capture keep its own width, and do not stretch it
to match the desktop one.

```html
<div class="side-by-side">
  <figure><img src="media/03-add-item-01-dialog-desktop.png" alt="Dialog at 1440 px"><figcaption>Desktop</figcaption></figure>
  <figure><img src="media/03-add-item-01-dialog-mobile.png" alt="Dialog at 390 px"><figcaption>Mobile</figcaption></figure>
</div>
```

```css
.steps, .side-by-side { display: flex; gap: 1rem; align-items: flex-start; overflow-x: auto; }
.steps figure, .side-by-side figure { margin: 0; flex: 0 1 auto; }
.steps img, .side-by-side img, video { max-width: 100%; max-height: 80vh; height: auto; }
```

On a narrow window, the row scrolls sideways instead of shrinking each capture
until it cannot be read.
