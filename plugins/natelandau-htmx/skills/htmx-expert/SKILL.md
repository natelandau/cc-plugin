---
name: htmx-expert
description: Use when writing, debugging, or reviewing htmx attributes (hx-get, hx-post, hx-swap, hx-target, hx-trigger, hx-boost), server-side HTML fragment responses, out-of-band swaps, htmx events, loading indicators, or hypermedia-driven patterns. Also when code or the user mentions any hx-* attribute or htmx class such as htmx-indicator or htmx-request, even without saying "htmx".
---

# htmx Expert

Target: htmx 2.x. Migration notes from 1.x: `references/v2-changes.md`.

Servers respond with HTML fragments, not JSON. The server owns application state; the browser renders HTML.

## Core Attributes Reference

### HTTP Verb Attributes

| Attribute   | Purpose              | Default Trigger      |
| ----------- | -------------------- | -------------------- |
| `hx-get`    | Issue GET request    | click                |
| `hx-post`   | Issue POST request   | click (form: submit) |
| `hx-put`    | Issue PUT request    | click                |
| `hx-patch`  | Issue PATCH request  | click                |
| `hx-delete` | Issue DELETE request | click                |

### hx-boost: Progressive Enhancement in One Attribute

`hx-boost="true"` on a parent converts all child links and forms to AJAX requests. Easiest way to add htmx to an existing multi-page app; no other attributes needed.

```html
<body hx-boost="true">
    <!-- All links now use AJAX with push-url, all forms submit via AJAX -->
    <nav>
        <a href="/dashboard">Dashboard</a>
        <!-- AJAX GET, swaps body -->
        <a href="/settings">Settings</a>
    </nav>
    <form action="/login" method="post">
        <!-- AJAX POST -->
        <input name="user" />
        <button type="submit">Login</button>
    </form>
</body>
```

Boosted requests swap `<body>` content and push the URL to history. Exclude an element: `hx-boost="false"`.

### Request Control

- **hx-trigger**: Customize when requests fire
    - Modifiers: `changed`, `delay:Xms`, `throttle:Xms`, `once`
    - Special triggers: `load`, `revealed`, `every Xs`
    - Extended: `from:<selector>`, `target:<selector>`
- **hx-include**: Include additional element values in request
- **hx-params**: Filter which parameters to send (`*`, `none`, `not <param>`, `<param>`)
- **hx-headers**: Add custom headers (JSON format)
- **hx-vals**: Add values to request (JSON format)
- **hx-encoding**: Set encoding (`multipart/form-data` for file uploads)

### Response Handling

- **hx-target**: Where to place response content
    - Extended selectors: `this`, `closest <sel>`, `next <sel>`, `previous <sel>`, `find <sel>`
- **hx-swap**: How to insert content
    - `innerHTML` (default), `outerHTML`, `beforebegin`, `afterbegin`, `beforeend`, `afterend`, `delete`, `none`
    - Modifiers: `swap:Xms`, `settle:Xms`, `scroll:top`, `show:top`, `transition:true`
- **hx-select**: Select subset of response to swap
- **hx-select-oob**: Select elements for out-of-band swaps

### State Management

- **hx-push-url**: Push URL to browser history
- **hx-replace-url**: Replace current URL in history
- **hx-history**: Control history snapshot behavior
- **hx-history-elt**: Specify element to snapshot
- **hx-preserve**: Keep an element unchanged during swaps (video/audio players, iframes, stateful DOM). Requires a stable `id`.

### UI Indicators

- **hx-indicator**: Element to show during request (add `htmx-indicator` class)
- **hx-disabled-elt**: Elements to disable during request

### Security & Control

- **hx-confirm**: Show confirmation dialog before request
- **hx-validate**: Enable HTML5 validation on non-form elements
- **hx-disable**: Disable htmx processing on element and descendants
- **hx-sync**: Coordinate requests between elements to prevent race conditions

    ```html
    <!-- Abort in-flight request when a new one starts (good for search/typeahead) -->
    <input hx-get="/search" hx-trigger="input changed delay:300ms" hx-sync="this:abort" hx-target="#results" />

    <!-- Queue requests on a form so rapid submits don't race -->
    <form hx-post="/save" hx-sync="this:queue first">...</form>

    <!-- Drop new requests while one is in flight -->
    <button hx-get="/data" hx-sync="this:drop">Load</button>
    ```

    Strategies: `drop` (ignore new), `abort` (cancel old), `replace` (cancel old, send new), `queue first`, `queue last`, `queue all`.

## Implementation Patterns

### Basic AJAX

```html
<button hx-get="/api/data" hx-target="#result" hx-swap="innerHTML">Load Data</button>
<div id="result"></div>
```

### Active Search

```html
<input
    type="search"
    name="q"
    hx-get="/search"
    hx-trigger="input changed delay:300ms, search"
    hx-target="#search-results"
    hx-sync="this:abort" />
<div id="search-results"></div>
```

Use `input changed`, not `keyup changed` (catches paste, autofill). `search` handles the clear button (X). `hx-sync="this:abort"` cancels stale in-flight requests.

### Infinite Scroll

```html
<div hx-get="/items?page=2" hx-trigger="revealed" hx-swap="afterend">Loading more...</div>
```

### Polling

```html
<div hx-get="/status" hx-trigger="every 5s" hx-swap="innerHTML">Status: Unknown</div>
```

### Form Submission

```html
<form hx-post="/submit" hx-target="#response" hx-swap="outerHTML">
    <input name="email" type="email" required />
    <button type="submit">Submit</button>
</form>
```

### Out-of-Band Updates

One response updates several elements:

```html
<!-- Main response (swapped into hx-target as normal) -->
<div id="main-content">Updated content</div>

<!-- OOB updates (swapped by matching id, regardless of hx-target) -->
<div id="notification" hx-swap-oob="true">New notification!</div>
<span id="counter" hx-swap-oob="true">42</span>
```

### Loading Indicators

```html
<button hx-get="/slow-endpoint" hx-indicator="#spinner">Load</button>
<img id="spinner" class="htmx-indicator" src="/spinner.gif" />
```

Indicator CSS:

```css
.htmx-indicator {
    opacity: 0;
    transition: opacity 200ms ease-in;
}
.htmx-request .htmx-indicator {
    opacity: 1;
}
```

Prefer a CSS-only spinner over an image file:

```css
.htmx-indicator {
    display: none;
}
.htmx-request .htmx-indicator {
    display: inline-block;
}
.spinner {
    width: 20px;
    height: 20px;
    border: 2px solid #f3f3f3;
    border-top: 2px solid #3d72d7;
    border-radius: 50%;
    animation: spin 1s linear infinite;
}
@keyframes spin {
    0% {
        transform: rotate(0deg);
    }
    100% {
        transform: rotate(360deg);
    }
}
```

### Form POST with Loading State

Combine `hx-indicator` and `hx-disabled-elt`:

```html
<form hx-post="/api/submit" hx-target="#result" hx-indicator="#spinner" hx-disabled-elt="find button">
    <input name="email" required />
    <button type="submit">
        Submit
        <span id="spinner" class="spinner htmx-indicator"></span>
    </button>
</form>
```

### Row Updates with closest

```html
<li id="item-1">
    <span>Item 1</span>
    <button hx-get="/api/update-item/1" hx-target="closest li" hx-swap="outerHTML">Update</button>
</li>
```

Server returns the complete `<li>` with its htmx attributes intact.

### Combining Multiple Triggers

```html
<div hx-get="/api/data" hx-trigger="load, every 5s, click from:#refresh-btn"></div>
```

## Template Organization

Most views need two versions: a full page (direct navigation) and a partial fragment (AJAX). Pick by the `HX-Request` header.

```python
if request.headers.get('HX-Request'):
    return render_template('_partial.html')
else:
    return render_template('full_page.html')
```

Prefix partial templates with `_` (`_search_results.html`, `_user_row.html`).

## Server Response Patterns

### Response Headers

| Header                    | Purpose                             |
| ------------------------- | ----------------------------------- |
| `HX-Location`             | Client-side redirect (with context) |
| `HX-Push-Url`             | Push URL to history                 |
| `HX-Redirect`             | Full page redirect                  |
| `HX-Refresh`              | Refresh the page                    |
| `HX-Reswap`               | Override hx-swap value              |
| `HX-Retarget`             | Override hx-target value            |
| `HX-Trigger`              | Trigger client-side events          |
| `HX-Trigger-After-Settle` | Trigger after settle                |
| `HX-Trigger-After-Swap`   | Trigger after swap                  |

## View Transitions

```html
<!-- Enable per-swap -->
<button hx-get="/page" hx-swap="innerHTML transition:true" hx-target="#content">Navigate</button>

<!-- Enable globally -->
<meta name="htmx-config" content='{"globalViewTransitions":true}' />
```

Style with CSS:

```css
::view-transition-old(root) {
    animation: fade-out 0.2s ease-out;
}
::view-transition-new(root) {
    animation: fade-in 0.2s ease-in;
}
```

Requires Chrome 111+ or Safari 18+. Elsewhere the swap works without animation.

## Events

### Key Events

| Event                      | When Fired                                  |
| -------------------------- | ------------------------------------------- |
| `htmx:load`                | Element loaded into DOM                     |
| `htmx:configRequest`       | Before request sent (modify params/headers) |
| `htmx:beforeRequest`       | Before AJAX request                         |
| `htmx:afterRequest`        | After AJAX request completes                |
| `htmx:beforeSwap`          | Before content swap                         |
| `htmx:afterSwap`           | After content swap                          |
| `htmx:afterSettle`         | After DOM settles                           |
| `htmx:confirm`             | Before confirmation dialog                  |
| `htmx:validation:validate` | Custom validation hook                      |

### Event Handling

`hx-on:` (htmx 2.x: single colon for DOM events, `::` for htmx events):

```html
<button hx-get="/data" hx-on::before-request="console.log('Starting...')" hx-on::after-swap="console.log('Done!')">
    Load
</button>

<!-- Standard DOM events use single colon -->
<button hx-on:click="console.log('clicked')">Click</button>
```

JavaScript:

```javascript
document.body.addEventListener("htmx:configRequest", function (evt) {
    evt.detail.headers["X-Custom-Header"] = "value";
});
```

## Security

1. Escape all user content in server templates (XSS).
2. Put `hx-disable` on untrusted content.
3. Restrict request origins: `htmx.config.selfRequestsOnly = true;`
4. Disable script processing: `htmx.config.allowScriptTags = false;`
5. Send CSRF tokens:
    ```html
    <body hx-headers='{"X-CSRF-Token": "{{ csrf_token }}"}'></body>
    ```
6. Add a Content Security Policy.

## Extensions

htmx 2.x ships extensions as separate packages. Usage of each: `references/extensions.md`.

```html
<script src="https://unpkg.com/htmx-ext-<name>@<version>/<name>.js"></script>
<body hx-ext="extension-name"></body>
```

Key extensions: **idiomorph** (morph swaps that preserve focus and form state), **sse** (Server-Sent Events), **ws** (WebSockets), **head-support** (merge `<head>` changes), **response-targets** (target by HTTP status), **preload** (prefetch on hover).

## Configuration

```javascript
htmx.config.defaultSwapStyle = "innerHTML";
htmx.config.timeout = 0;
htmx.config.historyCacheSize = 10;
htmx.config.globalViewTransitions = false;
htmx.config.scrollBehavior = "instant"; // or 'smooth', 'auto'
htmx.config.selfRequestsOnly = true; // recommended for security
htmx.config.allowScriptTags = false; // recommended for security
htmx.config.allowEval = true;
```

Or meta tag: `<meta name="htmx-config" content='{"selfRequestsOnly":true}' />`

## Debugging

```javascript
htmx.logAll();
```

Check Network tab headers: `HX-Request`, `HX-Target`, `HX-Trigger`, `HX-Current-URL`

## Third-Party Integration

```javascript
htmx.onLoad(function (content) {
    content.querySelectorAll(".datepicker").forEach((el) => new Datepicker(el));
});
htmx.process(document.getElementById("new-content")); // for programmatically added content
```

## Common Gotchas

1. Keep element IDs stable for CSS transitions and OOB swaps.
2. The default swap delay is 0ms. Use `swap:100ms` for transitions.
3. htmx events bubble. Read the data from `event.detail`.
4. Only named inputs are included in requests.
5. History snapshots store innerHTML, not the full DOM state.
6. htmx does not work over `file://`. Always serve over HTTP.

## Progressive Enhancement

```html
<form action="/search" method="POST">
    <input name="q" hx-get="/search" hx-trigger="input changed delay:300ms" hx-target="#results" />
    <button type="submit">Search</button>
</form>
<div id="results"></div>
```

Without JavaScript: form submission. With JavaScript: AJAX.
