---
name: accessibility
description: Use when building, reviewing, or auditing web UI for accessibility, including ARIA roles, keyboard navigation, focus management, color contrast, form labeling, target sizes, or WCAG 2.2 compliance. Also use when the user mentions a11y, screen readers, semantic HTML, focus traps, alt text, or asks "is this accessible", even if they do not say "accessibility" explicitly. Especially relevant when working on htmx fragments or daisyUI components.
paths:
  - "**/*.html"
  - "**/*.jinja"
  - "**/*.jinja2"
  - "**/*.j2"
---

# Accessibility (WCAG 2.2)

Make web interfaces Perceivable, Operable, Understandable, and Robust (POUR)
for everyone, including people who use screen readers, switch controls, or
keyboard-only navigation. This skill covers the technical implementation of
the WCAG 2.2 Level AA success criteria for the web (HTML, ARIA, CSS). Native
iOS and Android accessibility traits are out of scope.

## When to use

- Defining or reviewing UI component markup (buttons, links, tabs, dialogs,
  forms).
- Auditing existing templates or htmx fragments for accessibility barriers.
- Implementing WCAG 2.2 criteria such as Target Size (Minimum) and Focus
  Appearance.
- Translating a design into correct semantic markup and ARIA attributes.

## Core concepts

- The POUR principles are the foundation of WCAG: Perceivable, Operable,
  Understandable, Robust.
- Use the native element (`<button>`, `<a>`, `<nav>`, `<label>`) before a
  generic container plus ARIA. Native elements carry focus, keyboard, and role
  behavior built in.
- The accessibility tree is what assistive technology reads. ARIA changes the
  tree, not the visuals.
- Focus management controls the order and visibility of the keyboard and
  screen-reader cursor, especially across dynamic content swaps.
- Every interactive control must expose an accessible name, a role, and, where
  stateful, its current value.

## Implementation checklist by principle

### Perceivable

- Text contrast meets 4.5:1 for normal text and 3:1 for large text or UI
  components.
- Non-text content (images, icons) has a text alternative. Decorative images
  use an empty `alt=""` or `aria-hidden="true"`.
- The layout reflows without loss of function up to 400% zoom.
- Color never carries meaning alone. Pair it with text, an icon, or a pattern.

### Operable

- Interactive targets are at least 24x24 CSS pixels (SC 2.5.8).
- Every interactive element is reachable by keyboard and has a visible,
  high-contrast focus indicator (SC 2.4.11, 2.4.13).
- Dragging movements have a single-pointer alternative.
- Dialogs trap focus while open and release it on close, through the `Escape`
  key or an explicit close button (SC 2.1.2).

### Understandable

- Navigation patterns stay consistent across pages.
- Form errors give a text description and a correction suggestion (SC 3.3.3).
- A process never asks for the same information twice (SC 3.3.7).

### Robust

- Use correct Name, Role, Value patterns so controls are programmatically
  determinable.
- Announce dynamic status changes with `aria-live` regions: `polite` for
  non-urgent updates, `assertive` for urgent ones.

## Patterns with htmx

htmx swaps content in place, which is where accessibility regressions hide.
Two things to watch:

- Announce swapped content. If a swap changes status (a saved indicator, a
  validation result), put the result inside an `aria-live="polite"` region
  that already exists in the DOM. Swapping the live region itself can suppress
  the announcement.
- Restore focus after a swap. When a swap removes the element that had focus
  (for example, a row replaced after an edit), move focus to a sensible
  target. Otherwise keyboard users drop back to the top of the document.

```html
<!-- A persistent live region; htmx writes results into it -->
<div id="form-status" aria-live="polite" class="sr-only"></div>

<form hx-post="/save" hx-target="#form-status" hx-swap="innerHTML">
  ...
</form>
```

## Examples

### Accessible search form

```html
<form role="search">
  <label for="search-input" class="sr-only">Search products</label>
  <input type="search" id="search-input" placeholder="Search..." />
  <button type="submit" aria-label="Submit search">
    <svg aria-hidden="true">...</svg>
  </button>
</form>
```

### Icon-only button

```html
<!-- The visible content is an icon, so the button needs an accessible name -->
<button type="button" aria-label="Delete item">
  <svg aria-hidden="true">...</svg>
</button>
```

### daisyUI modal with contained focus

daisyUI's `<dialog class="modal">` uses the native `<dialog>` element, which
traps focus and closes on `Escape` when opened with `showModal()`. Prefer it
over a `div`-based modal, because the native element handles the hard parts.

```html
<dialog id="confirm" class="modal">
  <div class="modal-box">
    <h3>Delete this item?</h3>
    <div class="modal-action">
      <form method="dialog">
        <button class="btn">Cancel</button>
        <button class="btn btn-error">Delete</button>
      </form>
    </div>
  </div>
</dialog>
```

## Anti-patterns to avoid

- A `<div>` or `<span>` with a click handler but no role, no `tabindex`, and
  no keyboard support. Use `<button>`.
- An error or state signaled only by a red border.
- A custom modal that lets keyboard users tab into the background content.
- Alt text that starts with "Image of" or "Picture of". The role is already
  announced.
- An `aria-live` container replaced during an update, which can swallow the
  announcement.

## Audit checklist

- [ ] Interactive targets meet the 24x24 CSS pixel minimum.
- [ ] Focus indicators are visible and high-contrast.
- [ ] Dialogs contain focus while open and release it on close (`Escape` or a
      close button).
- [ ] Dropdowns and menus restore focus to the trigger element on close.
- [ ] Forms give text-based error messages and suggestions.
- [ ] Every icon-only button has a descriptive accessible name.
- [ ] Content reflows correctly at 400% zoom.
- [ ] Dynamic updates land in a persistent `aria-live` region.

## References

- [WCAG 2.2 Guidelines](https://www.w3.org/TR/WCAG22/)
- [WAI-ARIA Authoring Practices](https://www.w3.org/WAI/ARIA/apg/)
- [MDN: ARIA](https://developer.mozilla.org/en-US/docs/Web/Accessibility/ARIA)
