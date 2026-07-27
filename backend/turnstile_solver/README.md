# `turnstile_solver`

A small library that solves a Cloudflare Turnstile challenge by driving a real
Chromium profile, and hands you back the token (and, optionally, whatever the
challenge page issues afterwards).

It was lifted out of SpotiFLAC's desktop `run_community_verification()`, where
the same logic was tangled up with bootstrap requests, a loopback callback
server and session exchange. Nothing here knows about SpotiFLAC, sessions or
InstaPlayer: it takes a URL, it returns a result.

---

## Requirements

| | |
|---|---|
| Python | 3.10+ |
| Browser | Chrome, Edge, Brave or Chromium **installed on the host** |
| Package | `pip install nodriver` |
| Headless hosts | `xvfb` (strongly recommended — see below) |

`nodriver` is imported lazily, so `import turnstile_solver` works without it —
you only hit `BrowserUnavailableError` when you actually try to solve.

On a desktop the browser runs headful with its window parked far off-screen
(`offscreen=True`, the default), so it stays out of your way without using
`--headless`, which Turnstile is hostile to. Servers and containers are
covered too — see [Headless hosts](#headless-hosts-docker-ci-a-vps).

---

## Quick start

```python
from turnstile_solver import solve

result = solve("https://example.com/challenge")
print(result.token)   # the cf-turnstile-response value
print(result.grant)   # whatever the page handed back afterwards, if anything
```

From async code (FastAPI, a bot, anything with a running loop):

```python
from turnstile_solver import solve_async

result = await solve_async("https://example.com/challenge")
```

The blocking `solve()` **refuses** to run inside a live event loop rather than
stalling it for the length of a solve. Use `solve_async`, or push it to a
worker thread with `asyncio.to_thread(solve, url)`.

From the shell:

```bash
python -m turnstile_solver https://example.com/challenge
python -m turnstile_solver https://example.com/challenge --json --verbose
python -m turnstile_solver https://example.com/challenge --show-window --attempts 5
python -m turnstile_solver https://example.com/challenge --no-headless   # on a server
```

The plain form prints the grant if there is one, else the token, so it pipes
cleanly; `--json` prints the whole result. Diagnostics go to stderr.

---

## The API

### `solve(url, *, sitekey=None, **overrides) -> SolveResult`
### `async solve_async(url, *, sitekey=None, **overrides) -> SolveResult`

One-shot helpers using the default configuration. Any `SolverConfig` field can
be passed as a keyword to override it for that call:

```python
result = solve(url, attempts=5, attempt_timeout=20, hold_open=3.0)
```

`sitekey` is optional and only used by the injection fallback (see below); when
omitted it is scraped from the page if and only if that fallback is reached.

### `TurnstileSolver(config=None)`

The same thing, bound to a configuration you reuse:

```python
from turnstile_solver import TurnstileSolver, SolverConfig

solver = TurnstileSolver(SolverConfig(
    profile_dir="/var/lib/myapp/chrome-profile",
    attempts=5,
    hold_open=3.0,
))

result = solver.solve(url)
result = await solver.solve_async(other_url, attempts=1)   # per-call override
```

Instances are cheap and hold no OS resources between calls — each solve starts
and stops its own browser.

### `SolveResult`

| Field | Meaning |
|---|---|
| `token` | The `cf-turnstile-response` value, or `None` |
| `grant` | Value the page issued after passing, or `None` |
| `attempts` | How many page loads it took |
| `elapsed` | Wall-clock seconds |
| `cached` | `True` if the token came from the cache, not a browser run |
| `headless` | Whether Chrome actually ran headless |

`bool(result)` is true when either a token or a grant is present, and
`result.value` gives the grant if there is one, else the token. Both matter
because some pages consume the token internally and never expose it to the
DOM — a grant with no token is still a success.

### `SolverConfig`

Frozen dataclass; every field has a working default.

| Field | Default | What it does |
|---|---|---|
| `chrome_path` | auto | Browser executable. `None` → `CHROME_PATH`/`BRAVE_PATH`, then the usual install paths, then `PATH` |
| `profile_dir` | temp | Chrome `--user-data-dir`. `None` → `TS_PROFILE_DIR`, else a temp dir |
| `offscreen` | `True` | Park the window at -32000,-32000 instead of showing it |
| `browser_args` | `()` | Extra Chrome flags, appended last |
| `headless` | `"auto"` | `"auto"`, `True` or `False` — see [Headless hosts](#headless-hosts-docker-ci-a-vps) |
| `use_xvfb` | `True` | May start an Xvfb virtual display on a headless Linux host |
| `xvfb_display` | `":99"` | `DISPLAY` for that server |
| `xvfb_screen` | `"1280x900x24"` | Its geometry |
| `xvfb_binary` | `"Xvfb"` | Executable name or path |
| `attempts` | `2` | Page reloads before giving up |
| `attempt_timeout` | `45.0` | Seconds of clicking/polling per attempt |
| `retry_delay` | `5.0` | Seconds between attempts |
| `widget_wait` | `20.0` | Seconds to wait for the page's own widget before forcing one |
| `max_clicks` | `2` | Checkbox clicks per attempt |
| `click_interval` | `12.0` | Seconds to wait for a token before clicking again |
| `hold_open` | `0.0` | Seconds to keep the tab alive after success |
| `capture_grant` | `True` | Watch the network and the address bar for a grant |
| `grant_keys` | `("grant", "token", "code")` | Keys treated as a grant, in priority order |
| `cache_ttl` | `900.0` | Token cache lifetime; `0` disables |

Rough worst case: `attempts × (widget_wait + attempt_timeout) + (attempts − 1) × retry_delay`,
about two and a half minutes with the defaults. In practice the widget shows up
well inside `widget_wait`, so a failing solve lands nearer 100s.

### Errors

Everything intentional derives from `SolverError`:

- `BrowserNotFoundError` — no Chromium-family browser on the host
- `BrowserUnavailableError` — found one but couldn't drive it (missing
  `nodriver`, launch failure, CDP failure)
- `DisplayUnavailableError` — `headless=False` on a host with no display
- `SolveTimeout` — every attempt came back empty
- `SitekeyNotFound` — only from `discover_sitekey(..., required=True)`

### Helpers

```python
from turnstile_solver import (
    clear_cache, discover_sitekey, extract_grant, find_browser, start_virtual_display,
)

discover_sitekey(url)                      # scrape a sitekey, or None
extract_grant(callback_url, ("grant",))    # pull a value out of a query/fragment
find_browser()                             # resolved browser path
start_virtual_display()                    # bring up Xvfb yourself; True if DISPLAY is usable
clear_cache()                              # drop every cached token
```

---

## How it works

1. **Launch.** Start Chrome via CDP with a *persistent* profile. That's
   deliberate: Cloudflare's clearance cookie lives in the profile, so a repeat
   solve against the same host is often instant or needs no interaction.
2. **Wait for the widget.** Poll up to `widget_wait` seconds for one the page
   rendered itself. Detection keys on the hidden `cf-turnstile-response` input
   Turnstile creates, **not** on finding its iframe: the iframe usually sits in
   a closed shadow root that no DOM query can reach, so its absence proves
   nothing. Pages often render several seconds in, behind a countdown.
3. **Or force one.** Only if nothing rendered, and never on top of an existing
   widget — a second `render()` into the same container orphans the first
   iframe and leaves it stuck on "Verifying…" forever. Rendering reuses the
   page's own container, `data-sitekey` and `data-callback` so its flow
   carries on; a separate mounted widget is the last resort for pages with no
   container at all, and is the *only* place a sitekey is needed.
4. **Click — inside the widget's own frame.** This matters more than it
   sounds. Turnstile's widget is a cross-origin iframe, which Chrome runs
   out-of-process: it gets its own renderer, its own render widget, and its
   own CDP target. `Input.dispatchMouseEvent` sent to the *page* target goes
   to the main frame's widget and is **not** hit-tested into a child frame's
   renderer — so a click at exactly the right screen coordinates reaches
   nothing at all, and the checkbox sits there unticked. The solver locates
   the checkbox inside the widget's own target and clicks it in that frame's
   coordinate space; a page-level click is only the fallback for a widget
   that has no separate target. Same story for the keyboard path.
   Mouse movement is still humanized — approach, pause, jitter — since a
   teleport-and-click reads as synthetic. Up to `max_clicks` per attempt,
   `click_interval` apart.
5. **Collect.** Poll `window._tsToken` / the `cf-turnstile-response` input for
   the token. With `capture_grant` on, also decode every JSON response for a
   `grant`/`token`/`code` key and watch `window.location` for the same in a
   query or fragment — pages usually POST the token to their own endpoint and
   act on the reply without it ever touching the URL.
6. **Retry.** On an empty attempt, reload onto a fresh tab and start over, up
   to `attempts` times.
7. **Hold.** With `hold_open` set, leave the tab alive that long after success
   so the page can finish the request it fires once the challenge passes.

Nothing here defeats the challenge cryptographically — it clicks a checkbox in
a real browser.

## Headless hosts (Docker, CI, a VPS)

A machine with no screen works, and you shouldn't have to configure anything
for it. The important part is *how* it works: **a real browser on a fake
screen, not a headless browser.** Chrome's `--headless` mode advertises itself
through a pile of fingerprintable tells, and Turnstile reads them — so the
default is to conjure up a display rather than give one up.

`resolve_headless()` runs once per launch and picks, in order:

1. **`TS_HEADLESS`** in the environment (`1`/`true`/`0`/`false`/`auto`) — lets
   a container decide without touching code. Ignored if you set `headless`
   explicitly in the config.
2. **An existing `DISPLAY`**, or a non-Linux host → headful. Nothing to do.
3. **Xvfb** → start a virtual display, run headful on it. This is the good
   path, and the one to aim for.
4. **Chrome's headless mode**, with a warning. Solve rates drop noticeably.

So: `apt-get install -y xvfb` and you land on step 3 automatically. No
`DISPLAY`, no wrapper script, no `xvfb-run` — the solver starts the server
itself, checks it came up, and shuts it down at exit.

```python
solve(url)                      # auto: Xvfb if it can, headless if it must
solve(url, headless=True)       # force headless, skip the display machinery
solve(url, headless=False)      # insist on a display; DisplayUnavailableError if none
solve(url, use_xvfb=False)      # never start Xvfb (→ headless on a bare server)
solve(url, xvfb_screen="1920x1080x24")
```

`headless=False` is the useful one for a production box: it turns a missing
Xvfb into a loud error at launch instead of a mysterious drop in solve rate
weeks later. `result.headless` records which mode actually ran.

### In this repo's Docker image

The backend image can carry the solver, off by default — the server never
imports it, and chromium plus xvfb add several hundred MB:

```bash
echo "WITH_SOLVER=1" >> backend/.env    # compose reads this for build args
docker compose build && docker compose up -d
```

Keep it in `.env`. `--build-arg WITH_SOLVER=1` works for a single build, but
the next plain `docker compose build` reverts to the default and produces an
image with no browser — which surfaces later as `no Chromium-based browser
found` from the solver, long after the build that caused it.

That installs `google-chrome-stable` (`chromium` on non-amd64, which Google
doesn't build for), `xvfb`, `fonts-liberation` and `nodriver`. Chrome rather
than Chromium on purpose: Turnstile scores the client, and a Chromium build on
a datacentre address is an unusual enough fingerprint to count against you. The
package itself is copied in either way; without the build arg it just has no
browser to drive. Then:

```bash
docker compose exec backend python -m turnstile_solver <url> --json
```

`TS_PROFILE_DIR` is set to `/data/chrome-profile` in the image, so the Chrome
profile — and with it Cloudflare's clearance cookie — lives on the data volume
and survives restarts.

### In someone else's image

```dockerfile
RUN apt-get update \
    && apt-get install -y --no-install-recommends chromium xvfb fonts-liberation \
    && rm -rf /var/lib/apt/lists/* \
    && pip install nodriver
ENV TS_PROFILE_DIR=/var/lib/turnstile-profile
```

Container details handled for you:

- `--no-sandbox` and `--disable-dev-shm-usage` when running as root or when
  `/.dockerenv` exists (Chrome won't start sandboxed as root, and the default
  64 MB `/dev/shm` crashes renderers). If you'd rather raise the limit than
  move shared memory to `/tmp`, `--shm-size=1g` on the container works too.
- The window is **not** parked off-screen on an Xvfb display we started —
  there's nobody to hide it from, and a window at -32000 on a screen with no
  window manager can leave the renderer unpainted.
- Timer throttling is disabled and every tab is brought to the front. Chrome
  throttles `setTimeout` and stops `requestAnimationFrame` completely in a
  window it believes nobody is looking at — which is every window on a bare
  Xvfb. A challenge page that arms its widget behind a countdown then never
  arms it at all. For the same reason the solver never minimizes the window.
- Stale `Singleton*` locks are cleared from the profile before launch.

Don't set `CHROME_PATH` unless you mean it — an explicit path is trusted
without an existence check, so a stale one turns auto-detection off and gives
you a launch failure instead. `/usr/bin/google-chrome-stable` and
`/usr/bin/chromium` are both found on their own.

### Checking a host can solve at all

```bash
docker compose exec backend python -m turnstile_solver.selftest
```

Serves a page locally using Cloudflare's official test sitekeys and tries to
solve it — about twenty seconds, and no real service involved. A host that
can't tick the test checkbox won't manage a real one, so this separates "the
solver is broken here" from "this client is being declined". `--dump` prints
the widget frame's DOM, its CDP targets and a screenshot; `--sitekey pass`
uses the non-interactive key.

## Caching

Successful tokens are cached process-wide for `cache_ttl` seconds, keyed by
`(sitekey, url)`. The cache is **skipped** whenever `capture_grant` is on or
`hold_open` is set: a cached token replays no page load, so it can produce
neither a grant nor the background side effects those options exist to wait
for. Since `capture_grant` defaults to `True`, the default configuration
effectively never caches — opt in with `capture_grant=False`.

## Recipes

**Just the token, cached:**

```python
result = solve(url, capture_grant=False)
```

**A challenge page that redirects to a callback carrying a grant:**

```python
result = solve(f"{challenge_url}&cb={callback_url}", hold_open=3.0)
grant = result.grant
```

The entry URL is scanned for a grant too, so if a caller already holds a
callback URL with one in it, that short-circuits immediately.

**A page that issues a differently-named value:**

```python
result = solve(url, grant_keys=("ticket", "session_token"))
```

**Debugging a page that won't solve** — watch it happen:

```python
result = solve(url, offscreen=False, attempts=1, attempt_timeout=60)
```

or `python -m turnstile_solver <url> --show-window -v`.

## Notes

- The cache and the Xvfb display are process-wide (module-level), shared
  across every `TurnstileSolver` instance. Only the first solve pays to start
  the display; it's torn down at interpreter exit.
- Solves are not safe to run concurrently against the *same* `profile_dir` —
  Chrome locks it. Give parallel solvers separate profile directories. Each
  solve *clears* the profile's stale `Singleton*` markers on the way in, since
  a container killed mid-solve leaves them behind and Chrome then tries to
  hand the URL to a browser that no longer exists.
- Each solve navigates in a newly created tab rather than reusing the one
  Chrome opens at startup. Reusing it is what produces
  `Session with given id not found` (CDP -32001) on a cold container.
- Only use this against services whose terms permit automated access.

## Tests

`../tests/test_turnstile_solver.py` covers the browser-free logic (grant
extraction, sitekey scraping, config resolution, caching, the event-loop
guard):

```bash
cd backend && python -m pytest tests/test_turnstile_solver.py -q
```
