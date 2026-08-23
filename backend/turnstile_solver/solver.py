"""Cloudflare Turnstile solver driven through CDP by ``nodriver``.

Nothing here defeats the challenge cryptographically. It drives a *real*
Chromium profile: open the page, wait for the widget, click the checkbox with
human-ish mouse motion, and read the resulting token — plus, optionally, any
grant the page hands back once it passes. The persistent profile means
Cloudflare's clearance cookie survives between runs, so repeat solves against
the same host are usually instant.

The core is async (:meth:`TurnstileSolver.solve_async`), because ``nodriver``
is; :meth:`TurnstileSolver.solve` is a blocking wrapper for scripts and worker
threads.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import inspect
import json
import logging
import random
import time
from dataclasses import dataclass, replace
from pathlib import Path
from types import ModuleType
from urllib.parse import parse_qsl, urlparse

from .config import DEFAULT_CONFIG, SolverConfig, clear_stale_profile_locks
from .errors import BrowserUnavailableError, SolveTimeout
from .sitekey import discover_sitekey

logger = logging.getLogger(__name__)

__all__ = ["SolveResult", "TurnstileSolver", "clear_cache", "solve", "solve_async"]


# --------------------------------------------------------------------------
# Result
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class SolveResult:
    """Outcome of a solve.

    ``token`` is the ``cf-turnstile-response`` value. ``grant`` is whatever
    the challenge page handed back afterwards (see
    :attr:`~turnstile_solver.SolverConfig.grant_keys`) and is ``None`` unless
    ``capture_grant`` was on. Either one alone counts as success: some pages
    consume the token internally and never expose it to the DOM, handing back
    only a grant.
    """

    token: str | None = None
    grant: str | None = None
    attempts: int = 0
    elapsed: float = 0.0
    cached: bool = False
    #: Whether Chrome ran headless — worth logging when a solve mysteriously
    #: starts failing on a server.
    headless: bool = False
    #: Page state captured when a solve failed: URL, title, iframes, whether
    #: Turnstile's script loaded, visible text. ``None`` on success.
    diagnostics: dict | None = None

    def __bool__(self) -> bool:
        return bool(self.token or self.grant)

    @property
    def value(self) -> str:
        """The grant if there is one, else the token. Empty string if neither."""
        return self.grant or self.token or ""


# --------------------------------------------------------------------------
# nodriver plumbing
# --------------------------------------------------------------------------

_nodriver: ModuleType | None = None
_cdp: ModuleType | None = None


def _patch_unknown_cdp_events(connection_module: ModuleType) -> None:
    """Swallow ``KeyError`` from CDP events ``nodriver`` doesn't know.

    Chrome ships new events faster than ``nodriver`` maps them, and an
    unmapped one otherwise kills the connection mid-solve.
    """
    if getattr(connection_module, "_turnstile_unknown_event_patch", False):
        return

    original = connection_module.Connection.process_event

    if inspect.iscoroutinefunction(original):

        async def patched(self, *args, **kwargs):
            try:
                return await original(self, *args, **kwargs)
            except KeyError as exc:
                logger.debug("ignoring unknown CDP event: %s", exc)
                return None

    else:

        def patched(self, *args, **kwargs):
            try:
                return original(self, *args, **kwargs)
            except KeyError as exc:
                logger.debug("ignoring unknown CDP event: %s", exc)
                return None

    connection_module.Connection.process_event = patched
    connection_module._turnstile_unknown_event_patch = True


def _load_nodriver() -> tuple[ModuleType, ModuleType]:
    """Import ``nodriver`` on first use, patched and quietened.

    Deferred so that merely importing this package costs nothing and stays
    possible on hosts where the optional dependency isn't installed.
    """
    global _nodriver, _cdp
    if _nodriver is not None and _cdp is not None:
        return _nodriver, _cdp
    try:
        import nodriver
        from nodriver import cdp
        from nodriver.core import connection
    except ImportError as exc:
        raise BrowserUnavailableError(
            "nodriver is required to solve challenges: pip install nodriver"
        ) from exc

    _patch_unknown_cdp_events(connection)
    # nodriver narrates every CDP frame at INFO and asyncio complains about
    # the transports it tears down; neither is the caller's problem.
    logging.getLogger("nodriver.core.connection").setLevel(logging.CRITICAL)
    logging.getLogger("asyncio").setLevel(logging.ERROR)

    _nodriver, _cdp = nodriver, cdp
    return nodriver, cdp


# --------------------------------------------------------------------------
# Page-side scripts
# --------------------------------------------------------------------------

_JS_GET_TOKEN = """
    (() => {
        if (window._tsToken) return window._tsToken;
        // getResponse() reads Turnstile's own state, so it works even when the
        // widget lives in a shadow root the DOM queries below can't see.
        try {
            if (window.turnstile && window.turnstile.getResponse) {
                const r = window._tsWidgetId
                    ? window.turnstile.getResponse(window._tsWidgetId)
                    : window.turnstile.getResponse();
                if (r) return r;
            }
        } catch (e) {}
        const inp = document.querySelector('[name="cf-turnstile-response"]');
        return (inp && inp.value) ? inp.value : null;
    })()
"""

# Turnstile can render its iframe inside a shadow root, where querySelectorAll
# never finds it. Walk open shadow roots too before concluding there's nothing
# there. (A *closed* root stays invisible — that's what the screenshot is for.)
_JS_COLLECT_FRAMES = """
    function collectFrames(root, out) {
        Array.prototype.forEach.call(root.querySelectorAll('iframe'), function (f) {
            out.push(f);
        });
        Array.prototype.forEach.call(root.querySelectorAll('*'), function (e) {
            if (e.shadowRoot) collectFrames(e.shadowRoot, out);
        });
        return out;
    }
"""

_JS_CURRENT_URL = """
    (() => {
        try { return window.location.href || document.location.href || ''; }
        catch (e) { return ''; }
    })()
"""

# Has Turnstile rendered a widget here — whether or not we can see its iframe?
#
# The iframe usually lives in a closed shadow root, invisible to any DOM query,
# so its absence proves nothing. What Turnstile *does* put in the light DOM is
# a hidden `cf-turnstile-response` input, created the moment render() is called
# and later filled with the token. That input is the reliable marker, and
# reading its value is also how the token comes back.
_JS_WIDGET_PRESENT = _JS_COLLECT_FRAMES + """
    JSON.stringify((() => {
        const input = document.querySelector('[name="cf-turnstile-response"]');
        if (input) {
            return {present: true, via: 'response-input', id: input.id || null,
                    solved: !!input.value};
        }
        const frames = collectFrames(document, []);
        for (const f of frames) {
            const src = f.src || f.getAttribute('src') || '';
            if (src.indexOf('challenges.cloudflare.com') === -1) continue;
            const r = f.getBoundingClientRect();
            if (r.width > 50 && r.height > 20) {
                return {present: true, via: 'iframe', solved: false};
            }
        }
        return {present: false};
    })())
"""

# Rect of the *visible* Cloudflare iframe — the proof a real widget exists.
# The size floor skips the invisible 1x1 telemetry frames Turnstile injects.
_JS_WIDGET_RECT = _JS_COLLECT_FRAMES + """
    JSON.stringify((() => {
        const frames = collectFrames(document, []);
        for (const f of frames) {
            const src = f.src || f.getAttribute('src') || '';
            if (src.indexOf('challenges.cloudflare.com') === -1) continue;
            const r = f.getBoundingClientRect();
            if (r.width > 50 && r.height > 20) return {x: r.x, y: r.y, w: r.width, h: r.height};
        }
        return null;
    })())
"""

# Where to click when no iframe can be found. The container the page declared
# is in the light DOM and sits exactly where the widget is drawn, so it gives
# us the right coordinates even when the widget itself is hidden from us
# inside a closed shadow root.
_JS_CLICK_TARGET = _JS_COLLECT_FRAMES + """
    JSON.stringify((() => {
        const frames = collectFrames(document, []);
        for (const f of frames) {
            const src = f.src || f.getAttribute('src') || '';
            if (src.indexOf('challenges.cloudflare.com') === -1) continue;
            const r = f.getBoundingClientRect();
            if (r.width > 50 && r.height > 20) {
                return {x: r.x, y: r.y, w: r.width, h: r.height, source: 'iframe'};
            }
        }
        const el = document.querySelector('.cf-turnstile,[data-sitekey]');
        if (el) {
            const r = el.getBoundingClientRect();
            if (r.width > 20 && r.height > 10) {
                return {x: r.x, y: r.y, w: r.width, h: r.height, source: 'container'};
            }
        }
        return null;
    })())
"""

# What the page actually looks like right now. The whole point is to answer
# "why did we not find a widget?" from a log line, without a screen to look at:
# did the page even load, is Turnstile's script there, what iframes exist, and
# what is the page telling a human?
_JS_DIAGNOSTICS = _JS_COLLECT_FRAMES + """
    JSON.stringify((() => {
        const frames = Array.prototype.map.call(
            collectFrames(document, []),
            (f) => {
                const r = f.getBoundingClientRect();
                const style = window.getComputedStyle(f);
                return {
                    src: (f.src || f.getAttribute('src') || '(none)').slice(0, 140),
                    w: Math.round(r.width),
                    h: Math.round(r.height),
                    hidden: style.display === 'none' || style.visibility === 'hidden',
                };
            }
        );
        const container = document.querySelector('.cf-turnstile,[data-sitekey]');
        const body = document.body;
        return {
            url: (location.href || '').slice(0, 300),
            title: document.title,
            ready: document.readyState,
            // If the page is hidden, its timers are throttled and rAF is
            // stopped outright — the usual reason a delayed widget never arms.
            visibility: document.visibilityState,
            focused: document.hasFocus(),
            container: container
                ? (function () {
                      const r = container.getBoundingClientRect();
                      return {
                          sitekey: container.getAttribute('data-sitekey') || null,
                          callback: container.getAttribute('data-callback') || null,
                          iframes: collectFrames(container, []).length,
                          // A rendered widget gives the container real size;
                          // 0x0 means Turnstile put nothing in it.
                          rect: [Math.round(r.x), Math.round(r.y),
                                 Math.round(r.width), Math.round(r.height)],
                          shadow: !!container.shadowRoot,
                          childNodes: container.childNodes.length,
                          html: (container.innerHTML || '').slice(0, 200),
                      };
                  })()
                : null,
            // Set if turnstile.render() returned an id when we forced it.
            forcedWidgetId: window._tsWidgetId || null,
            turnstile: typeof window.turnstile,
            frames: frames,
            responseInputs: document.querySelectorAll('[name="cf-turnstile-response"]').length,
            widgetDivs: document.querySelectorAll('.cf-turnstile,[data-sitekey]').length,
            scripts: Array.prototype.filter.call(
                document.querySelectorAll('script[src]'),
                (s) => s.src.indexOf('challenges.cloudflare.com') !== -1
            ).length,
            text: (body ? body.innerText || '' : '').replace(/\\s+/g, ' ').slice(0, 400),
            htmlBytes: document.documentElement ? document.documentElement.outerHTML.length : 0,
        };
    })())
"""

# Preferred fallback: render into the container the page already put there.
#
# A page that declares a widget but never renders it (its countdown never
# fired, say) has all the information we need sitting in the DOM — the sitekey
# and, per Turnstile's explicit-render contract, often a data-callback naming
# the function it wants called with the token. Rendering into *its* container
# and invoking *its* callback keeps the page's own flow intact, so it goes on
# to call its verify endpoint and mint a grant. Mounting a widget of our own
# elsewhere gets a token nobody asked for and nobody consumes.
_JS_ADOPT_WIDGET = """
    JSON.stringify((() => {
        if (typeof window.turnstile === 'undefined') {
            return {ok: false, why: 'turnstile api not loaded'};
        }
        const el = document.querySelector('.cf-turnstile,[data-sitekey]');
        if (!el) return {ok: false, why: 'no widget container on the page'};
        // Never render twice into one container. The first widget's iframe is
        // in a closed shadow root we can't see, but its response input is
        // right here — and a second render orphans that iframe, leaving
        // Turnstile posting messages to a dead window and the widget stuck
        // on "Verifying..." forever.
        if (document.querySelector('[name="cf-turnstile-response"]')) {
            return {ok: true, why: 'already rendered'};
        }

        const sitekey = el.getAttribute('data-sitekey') || __SITEKEY__;
        if (!sitekey) return {ok: false, why: 'no sitekey on the container'};
        const cbName = el.getAttribute('data-callback');
        window._tsToken = null;
        try {
            window._tsWidgetId = window.turnstile.render(el, {
                sitekey: sitekey,
                callback: function (token) {
                    window._tsToken = token;
                    if (cbName && typeof window[cbName] === 'function') {
                        try { window[cbName](token); } catch (e) {}
                    }
                }
            });
            return {ok: true, why: 'rendered', sitekey: sitekey, callback: cbName};
        } catch (e) {
            return {ok: false, why: String(e)};
        }
    })())
"""

# Last resort for pages with no container at all: mount one in the top-left
# corner and stash the token on `window._tsToken`.
_JS_INJECT_WIDGET = """
    (() => {
        if (document.getElementById('_ts_box')) return;
        window._tsToken = null;
        const wrap = document.createElement('div');
        wrap.id = '_ts_box';
        wrap.style = 'position:fixed;top:20px;left:20px;z-index:2147483647;';
        document.body.appendChild(wrap);
        window._tsLoad = function () {
            turnstile.render('#_ts_box', {
                sitekey: __SITEKEY__,
                callback: function (token) { window._tsToken = token; }
            });
        };
        const s = document.createElement('script');
        s.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js?onload=_tsLoad&render=explicit';
        s.async = true;
        document.head.appendChild(s);
    })()
"""


def _explain(info: dict | None) -> str:
    """One-line account of a failed page, for the exception message.

    The caller usually sees nothing but this string in a log, so it has to
    carry enough to tell "the page never loaded" apart from "the page loaded
    and told us no".
    """
    if not info:
        return "no page diagnostics available"
    if info.get("error"):
        return str(info["error"])

    frames = info.get("frames") or []
    cloudflare = [f for f in frames if "challenges.cloudflare.com" in (f.get("src") or "")]
    parts = [
        f"title={info.get('title')!r}",
        f"ready={info.get('ready')}",
        f"visibility={info.get('visibility')}",
        f"turnstile={info.get('turnstile')}",
        f"container={info.get('container')}",
        f"cf-iframes={len(cloudflare)}/{len(frames)}",
    ]
    cdp_frames = info.get("cdpFrames")
    if cdp_frames:
        # Says whether Turnstile's iframe exists and what it managed to load.
        parts.append(f"cdp-frames={[f.get('url') for f in cdp_frames]}")
    if info.get("widgetText"):
        # The widget's own words — the only place it reports its verdict.
        parts.append(f"widget-says={info['widgetText']!r}")
    # For a widget stuck on "Verifying…", these two are the whole story.
    if info.get("cfRequests"):
        parts.append(f"cf-requests={info['cfRequests'][:10]}")
    if info.get("netFailures"):
        parts.append(f"net-failures={info['netFailures'][:8]}")
    if cloudflare:
        sizes = ", ".join(f"{f.get('w')}x{f.get('h')}" for f in cloudflare)
        parts.append(f"cf-iframe-sizes=[{sizes}]")
    # Turnstile's own error codes land here; they name the cause outright.
    console = [
        line
        for line in (info.get("console") or [])
        if "turnstile" in line.lower() or "cloudflare" in line.lower() or "error" in line.lower()
    ]
    if console:
        parts.append(f"console={console[:6]}")
    text = (info.get("text") or "").strip()
    if text:
        parts.append(f"page-text={text[:180]!r}")
    return " ".join(parts)


def extract_grant(url: str, keys: tuple[str, ...]) -> str | None:
    """First of ``keys`` present in ``url``'s query or fragment, or ``None``."""
    if not url:
        return None
    try:
        parsed = urlparse(url)
    except Exception:
        return None
    for source in (parsed.query, parsed.fragment):
        if not source:
            continue
        params = dict(parse_qsl(source, keep_blank_values=True))
        for key in keys:
            value = params.get(key)
            if value and value.strip():
                return value.strip()
    return None


# --------------------------------------------------------------------------
# One browser session
# --------------------------------------------------------------------------


class _Session:
    """A single browser lifetime: one launch, up to ``config.attempts`` tries."""

    def __init__(self, url: str, sitekey: str | None, config: SolverConfig) -> None:
        self.url = url
        self.sitekey = sitekey
        self.config = config
        self.browser = None
        self.page = None
        self.headless = False
        # Seeded from the entry URL: the caller may already be handing us a
        # callback URL that carries the grant.
        self.grant = extract_grant(url, config.grant_keys)
        self.network_grant: str | None = None
        #: Set once a value arrived under the highest-priority grant key.
        self.grant_is_final = False
        self.last_diagnostics: dict | None = None
        #: Console output and browser log entries, bounded and deduplicated.
        self.console: list[str] = []
        #: Requests that failed or returned an error status.
        self.net_failures: list[str] = []
        #: Every request to challenges.cloudflare.com, with its status — the
        #: conversation a stalled widget is actually having.
        self.cf_requests: list[str] = []
        self._request_urls: dict[str, str] = {}

    # -- browser lifecycle -------------------------------------------------

    async def __aenter__(self) -> _Session:
        uc, _ = _load_nodriver()
        config = self.config
        # Brings up Xvfb when that's the better option; see resolve_headless().
        self.headless = config.resolve_headless()
        if self.headless:
            logger.info("running Chrome headless — expect a lower solve rate")

        profile_dir = config.resolved_profile_dir()
        clear_stale_profile_locks(profile_dir)
        try:
            self.browser = await uc.start(
                config=self._browser_config(
                    uc, profile_dir, config.chrome_args(self.headless)
                )
            )
        except Exception as exc:
            raise BrowserUnavailableError(f"could not launch the browser: {exc}") from exc

        # Let target discovery settle. nodriver populates browser.targets from
        # CDP events after start() returns, and navigating against a
        # half-populated list is what produces "Session with given id not
        # found" on a slow/cold container start.
        with contextlib.suppress(Exception):
            await self.browser.wait(1)
        return self

    def _browser_config(self, uc, profile_dir: str, args: list[str]):
        """Build nodriver's Config, minus any flag in ``drop_browser_args``.

        nodriver keeps its own default switches on the Config object, so the
        only way to *remove* one is to reach in and filter the list. Guarded:
        if the attribute isn't where we expect it on this version, we simply
        keep nodriver's defaults rather than failing to launch.
        """
        config = self.config
        browser_config = uc.Config(
            user_data_dir=profile_dir,
            headless=self.headless,
            browser_executable_path=config.resolved_chrome_path(),
            browser_args=list(args),
        )
        if not config.drop_browser_args:
            return browser_config

        defaults = getattr(browser_config, "_default_browser_args", None)
        if not isinstance(defaults, list):
            logger.debug("nodriver defaults not filterable on this version")
            return browser_config

        kept, dropped = [], []
        for arg in defaults:
            if any(arg.startswith(prefix) for prefix in config.drop_browser_args):
                dropped.append(arg)
            else:
                kept.append(arg)
        if dropped:
            browser_config._default_browser_args = kept
            logger.info("dropped driver default flags: %s", dropped)
        return browser_config

    async def __aexit__(self, *_exc_info) -> None:
        if self.browser is not None:
            with contextlib.suppress(Exception):
                self.browser.stop()

    # -- page helpers ------------------------------------------------------

    async def open_page(self) -> None:
        """(Re)open the target URL on a fresh tab with capture wired up."""
        previous = self.page
        self.page = await self._open_tab()
        # Close the old tab only once its replacement exists: closing the last
        # remaining tab can take the whole browser down with it.
        if previous is not None:
            with contextlib.suppress(Exception):
                await previous.close()
        # Make the tab the active one. A page that is merely open but never
        # foregrounded reports document.hidden, which throttles setTimeout and
        # stops requestAnimationFrame entirely — enough to freeze the countdown
        # a challenge page runs before arming its widget.
        with contextlib.suppress(Exception):
            await self.page.bring_to_front()
        await self._enable_network_capture()
        await self._enable_console_capture()
        # A little pointer activity, for the same reason: some pages hold off
        # until they've seen a sign of life.
        with contextlib.suppress(Exception):
            await self.page.mouse_move(
                640 + random.uniform(-40, 40), 400 + random.uniform(-40, 40)
            )

    async def _enable_proxy_auth(self, tab) -> None:
        """Answer the proxy's auth challenge for this tab.

        ``--proxy-server`` carries no credentials, so Chrome asks over CDP the
        first time the proxy demands them. Intercepting requests to answer that
        means every request now needs an explicit continue — miss one and the
        page simply hangs, so both handlers matter.
        """
        _, cdp = _load_nodriver()
        _, username, password = self.config.proxy_parts()
        if not username:
            return

        async def on_auth(event) -> None:
            with contextlib.suppress(Exception):
                await tab.send(
                    cdp.fetch.continue_with_auth(
                        request_id=event.request_id,
                        auth_challenge_response=cdp.fetch.AuthChallengeResponse(
                            response="ProvideCredentials",
                            username=username,
                            password=password or "",
                        ),
                    )
                )

        async def on_paused(event) -> None:
            with contextlib.suppress(Exception):
                await tab.send(cdp.fetch.continue_request(request_id=event.request_id))

        try:
            tab.add_handler(cdp.fetch.AuthRequired, on_auth)
            tab.add_handler(cdp.fetch.RequestPaused, on_paused)
            await tab.send(cdp.fetch.enable(handle_auth_requests=True))
            logger.debug("proxy authentication armed")
        except Exception as exc:
            logger.warning("could not arm proxy authentication: %s", exc)

    async def _open_tab(self):
        """Navigate to the target URL in a *new* tab, retrying CDP failures.

        ``browser.get()`` without ``new_tab`` reuses the first ``page`` target
        nodriver saw at startup. In a container that target is regularly gone
        or replaced by the time we navigate, and the attempt fails with
        ``Session with given id not found`` (CDP -32001). Creating a tab goes
        through the browser-level connection instead, which stays valid for
        the life of the process.

        Older nodriver builds don't take ``new_tab``; fall back to the plain
        call there rather than hard-failing.
        """
        _, cdp = _load_nodriver()
        _, proxy_user, _ = self.config.proxy_parts()

        last_exc: Exception | None = None
        for attempt in range(1, 4):
            try:
                if proxy_user:
                    # Auth has to be armed before the first request leaves, so
                    # land on a blank page, wire it up, then navigate.
                    tab = await self.browser.get("about:blank", new_tab=True)
                    await self._enable_proxy_auth(tab)
                    await tab.send(cdp.page.navigate(self.url))
                    return tab
                try:
                    return await self.browser.get(self.url, new_tab=True)
                except TypeError:
                    return await self.browser.get(self.url)
            except Exception as exc:
                last_exc = exc
                logger.debug("could not open a tab (attempt %d/3): %s", attempt, exc)
                await asyncio.sleep(1.0)
        raise BrowserUnavailableError(f"could not open {self.url}: {last_exc}")

    async def _enable_console_capture(self) -> None:
        """Collect console output and browser log entries.

        Turnstile announces its own failures here with a numeric code —
        ``[Cloudflare Turnstile] Error: 110200`` for a domain the sitekey
        doesn't cover, ``300xxx`` for a client-side execution failure, and so
        on. When a widget silently refuses to appear, this is usually the only
        place that says why.
        """
        _, cdp = _load_nodriver()
        # Runtime.enable is off by default and that is deliberate. Enabling it
        # is one of the classic ways a page catches an automated browser: with
        # the domain on, objects logged to the console get serialised for the
        # debugger, so a script can plant a getter on a property and watch it
        # fire. Anti-bot vendors have shipped exactly that check for years.
        # Console output is worth having while debugging, not while trying to
        # look like a person.
        if self.config.capture_console:
            try:
                await self.page.send(cdp.runtime.enable())
                self.page.add_handler(cdp.runtime.ConsoleAPICalled, self._on_console)
            except Exception as exc:
                logger.debug("console capture unavailable: %s", exc)
        try:
            await self.page.send(cdp.log.enable())
            self.page.add_handler(cdp.log.EntryAdded, self._on_log_entry)
        except Exception as exc:
            logger.debug("browser log capture unavailable: %s", exc)

    def _record_console(self, level: str, text: str) -> None:
        text = (text or "").strip()
        if not text or len(self.console) >= 40:
            return
        entry = f"[{level}] {text[:300]}"
        if entry not in self.console:
            self.console.append(entry)

    async def _on_console(self, event) -> None:
        try:
            parts = []
            for arg in getattr(event, "args", None) or []:
                value = getattr(arg, "value", None)
                parts.append(str(value) if value is not None else getattr(arg, "type_", "?"))
            self._record_console(str(getattr(event, "type_", "log")), " ".join(parts))
        except Exception:
            pass

    async def _on_log_entry(self, event) -> None:
        try:
            entry = event.entry
            self._record_console(str(getattr(entry, "level", "info")), getattr(entry, "text", ""))
        except Exception:
            pass

    async def _enable_network_capture(self) -> None:
        """Watch the network, for two reasons.

        The grant: pages POST the token to their own verify endpoint and act
        on the JSON reply without ever putting it in the URL, so sniffing the
        response is the only way to see it.

        The failures: a widget stuck on "Verifying…" has already accepted the
        click and is waiting on its own calls to Cloudflare. Whether those
        calls are failing — and how — is the only thing that distinguishes a
        blocked request from a rejected client, and neither shows up anywhere
        in the DOM.
        """
        _, cdp = _load_nodriver()
        try:
            await self.page.send(cdp.network.enable())
            self.page.add_handler(cdp.network.RequestWillBeSent, self._on_request)
            self.page.add_handler(cdp.network.ResponseReceived, self._on_response)
            self.page.add_handler(cdp.network.LoadingFailed, self._on_loading_failed)
        except Exception as exc:
            logger.debug("network capture unavailable: %s", exc)

    def _note_request(self, line: str) -> None:
        if len(self.net_failures) < 40 and line not in self.net_failures:
            self.net_failures.append(line)

    async def _on_request(self, event) -> None:
        # LoadingFailed carries no URL, only a request id, so remember them.
        try:
            if len(self._request_urls) < 600:
                self._request_urls[str(event.request_id)] = str(event.request.url)[:200]
        except Exception:
            pass

    async def _on_loading_failed(self, event) -> None:
        try:
            url = self._request_urls.get(str(event.request_id), "(unknown url)")
            blocked = getattr(event, "blocked_reason", None)
            detail = getattr(event, "error_text", "") or "failed"
            if blocked:
                detail = f"{detail} (blocked: {blocked})"
            self._note_request(f"FAILED {url} — {detail}")
            if "challenges.cloudflare.com" in url:
                logger.warning("a Turnstile request failed: %s — %s", url, detail)
        except Exception:
            pass

    async def _on_response(self, event) -> None:
        if self.page is None:
            return

        # Record the outcome first, whatever it is: a widget that never
        # finishes verifying is a story told entirely in its own requests.
        try:
            url = str(getattr(event.response, "url", "") or "")
            status = int(getattr(event.response, "status", 0) or 0)
            if "challenges.cloudflare.com" in url:
                self.cf_requests.append(f"{status} {url.split('?')[0][:110]}")
                if status >= 400:
                    logger.warning("Turnstile request returned HTTP %d: %s", status, url)
            if status >= 400:
                self._note_request(f"HTTP {status} {url[:160]}")
        except Exception:
            pass

        # Keep listening after a lower-priority match: an unrelated response
        # carrying a "token" must not shadow the real "grant" still to come.
        if self.grant_is_final or not self.config.capture_grant:
            return
        _, cdp = _load_nodriver()
        try:
            mime = (getattr(event.response, "mime_type", "") or "").lower()
            if "json" not in mime:
                return
            body, is_base64 = await self.page.send(
                cdp.network.get_response_body(event.request_id)
            )
            if is_base64:
                body = base64.b64decode(body).decode("utf-8", errors="ignore")
            data = json.loads(body)
            if not isinstance(data, dict):
                return
            for rank, key in enumerate(self.config.grant_keys):
                value = data.get(key)
                if not isinstance(value, str) or not value.strip():
                    continue
                if rank == 0:  # the real thing; stop looking
                    self.network_grant = value.strip()
                    self.grant_is_final = True
                elif self.network_grant is None:
                    self.network_grant = value.strip()  # provisional
                logger.info("captured a grant candidate from the page (key=%r)", key)
                return
        except Exception:
            pass  # a body we can't read is just one we skip

    async def _eval(self, script: str):
        try:
            return await self.page.evaluate(script)
        except Exception as exc:
            logger.debug("page evaluate failed: %s", exc)
            return None

    async def get_token(self) -> str | None:
        return await self._eval(_JS_GET_TOKEN)

    async def _rect(self, script: str) -> dict | None:
        raw = await self._eval(script)
        if raw and raw != "null":
            with contextlib.suppress(ValueError, TypeError):
                return json.loads(raw)
        return None

    async def widget_rect(self) -> dict | None:
        """Rect of a real Cloudflare widget iframe, or ``None``."""
        return await self._rect(_JS_WIDGET_RECT)

    async def click_target(self) -> dict | None:
        """Where to aim: the widget iframe, else the page's own container."""
        return await self._rect(_JS_CLICK_TARGET)

    async def refresh_grant(self) -> str | None:
        """Re-check both grant channels (network sniff, then the address bar)."""
        if not self.config.capture_grant:
            return self.grant
        if self.network_grant:
            self.grant = self.network_grant
            return self.grant
        url = await self._eval(_JS_CURRENT_URL)
        found = extract_grant(url or "", self.config.grant_keys)
        if found:
            self.grant = found
        return self.grant

    async def dump_artifacts(self, label: str = "challenge") -> str | None:
        """Write a screenshot, the DOM and the diagnostics JSON to
        ``config.diagnostics_dir``. No-op when it isn't configured.

        A screenshot is worth a great deal here: the page may be showing a
        block notice, a rate-limit message, or an error in plain text that no
        amount of DOM querying would have made obvious.
        """
        directory = self.config.diagnostics_dir
        if not directory or self.page is None:
            return None
        try:
            path = Path(directory)
            path.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            base = path / f"{label}-{stamp}"

            with contextlib.suppress(Exception):
                await self.page.save_screenshot(f"{base}.png")
            with contextlib.suppress(Exception):
                html = await self.page.get_content()
                Path(f"{base}.html").write_text(html or "", encoding="utf-8")
            Path(f"{base}.json").write_text(
                json.dumps(self.last_diagnostics or {}, indent=2), encoding="utf-8"
            )
            logger.warning("wrote failure diagnostics to %s.*", base)
            return str(base)
        except Exception as exc:
            logger.debug("could not write diagnostics: %s", exc)
            return None

    async def diagnostics(self) -> dict:
        """Snapshot of the page, for working out why a solve went nowhere."""
        raw = await self._eval(_JS_DIAGNOSTICS)
        if not raw:
            return {"error": "page did not respond to evaluate", "console": list(self.console)}
        try:
            info = json.loads(raw)
        except (ValueError, TypeError):
            return {"error": "diagnostics were not valid JSON", "console": list(self.console)}
        info["console"] = list(self.console)
        # The one view that sees through closed shadow roots.
        info["cdpFrames"] = await self.cdp_frames()
        info["netFailures"] = list(self.net_failures)
        info["cfRequests"] = list(self.cf_requests)
        info["widgetText"] = await self.widget_text()
        return info

    async def log_missing_widget(self) -> dict:
        """Report a page that never produced a widget, at WARNING.

        This is the one failure that needs explaining from a log file alone,
        so it prints the page's own state rather than just "no widget".
        """
        info = await self.diagnostics()
        frames = info.get("frames") or []
        logger.warning(
            "no Turnstile widget on %s — title=%r ready=%s visibility=%s focused=%s "
            "turnstile=%s cf-scripts=%d container=%s iframes=%s console=%s page-text=%r",
            info.get("url", self.url),
            info.get("title"),
            info.get("ready"),
            info.get("visibility"),
            info.get("focused"),
            info.get("turnstile"),
            info.get("scripts", 0),
            info.get("container"),
            [f"{f.get('src', '')[:60]} {f.get('w')}x{f.get('h')}" for f in frames] or "none",
            info.get("console") or "none",
            (info.get("text") or "")[:200],
        )
        return info

    async def widget_present(self) -> dict:
        """Has Turnstile rendered a widget on this page? See ``_JS_WIDGET_PRESENT``."""
        raw = await self._eval(_JS_WIDGET_PRESENT)
        if raw:
            with contextlib.suppress(ValueError, TypeError):
                return json.loads(raw)
        return {"present": False}

    async def wait_for_widget(self, seconds: float | None = None) -> bool:
        """Poll up to ``widget_wait`` seconds for the page's own widget.

        Pages commonly render Turnstile a few seconds in — behind a countdown,
        say — and a cold browser in a container is slower still, so give
        theirs a chance before forcing one. Getting this wait right matters
        more than it looks: conclude too early and we render a second widget
        over a perfectly good one and break it.
        """
        deadline = time.monotonic() + (
            self.config.widget_wait if seconds is None else seconds
        )
        while True:
            state = await self.widget_present()
            if state.get("present"):
                logger.info("page rendered its own widget (via %s)", state.get("via"))
                return True
            if time.monotonic() >= deadline:
                return False
            await asyncio.sleep(0.5)

    async def force_widget(self) -> None:
        """Get a widget on screen when the page failed to render its own.

        Tries the page's own container first (see ``_JS_ADOPT_WIDGET``) and
        only falls back to mounting a separate widget, which rarely helps a
        page that runs its own verification.
        """
        sitekey = json.dumps(self.sitekey or "")
        raw = await self._eval(_JS_ADOPT_WIDGET.replace("__SITEKEY__", sitekey))
        outcome = {}
        if raw:
            with contextlib.suppress(ValueError, TypeError):
                outcome = json.loads(raw)

        if outcome.get("ok"):
            logger.info(
                "rendered into the page's own widget container (%s, callback=%s)",
                outcome.get("why"),
                outcome.get("callback"),
            )
            await asyncio.sleep(2.0)
            return

        logger.info(
            "could not use the page's widget (%s); mounting a separate one",
            outcome.get("why", "unknown"),
        )
        await self._eval(_JS_INJECT_WIDGET.replace("__SITEKEY__", sitekey))
        await asyncio.sleep(2.0)  # let api.js load and render

    async def element_at(self, rect: dict | None) -> str | None:
        """What sits under the click point — proof the aim is right.

        If this isn't the widget or its container, the clicks are hitting
        something else (an overlay, the page background) and no amount of
        clicking will ever solve anything.
        """
        if not rect:
            return None
        x = round(rect["x"] + 28)
        y = round(rect["y"] + rect["h"] / 2)
        return await self._eval(f"""
            (() => {{
                const el = document.elementFromPoint({x}, {y});
                if (!el) return 'nothing';
                const box = document.querySelector('.cf-turnstile,[data-sitekey]');
                const inside = box && (box === el || box.contains(el));
                return (inside ? 'widget:' : 'other:') + el.tagName
                     + (el.id ? '#' + el.id : '')
                     + (el.className && typeof el.className === 'string'
                        ? '.' + el.className.split(' ')[0] : '');
            }})()
        """)

    async def cdp_frames(self) -> list[dict]:
        """Every frame in the page, straight from CDP.

        The authoritative view: unlike any DOM query it sees through closed
        shadow roots, so it answers whether Turnstile's iframe exists at all
        and — crucially — whether it actually loaded
        ``challenges.cloudflare.com`` or is sitting on ``about:blank``.
        """
        _, cdp = _load_nodriver()
        frames: list[dict] = []

        def walk(node, depth: int = 0) -> None:
            frame = getattr(node, "frame", None)
            if frame is not None:
                frames.append({
                    "depth": depth,
                    "url": (getattr(frame, "url", "") or "")[:120],
                    "name": getattr(frame, "name", None) or None,
                })
            for child in getattr(node, "child_frames", None) or []:
                walk(child, depth + 1)

        try:
            walk(await self.page.send(cdp.page.get_frame_tree()))
        except Exception as exc:
            logger.debug("could not read the frame tree: %s", exc)

        # With site isolation on, a cross-origin iframe is a separate target
        # and never appears in this page's frame tree — so check the browser's
        # target list too, or we'd wrongly conclude the iframe doesn't exist.
        try:
            for target in getattr(self.browser, "targets", None) or []:
                kind = str(getattr(target, "type_", "") or "")
                url = str(getattr(target, "url", "") or "")
                if kind in ("iframe", "page") and url and url != self.url:
                    frames.append({"depth": -1, "url": url[:120], "name": f"target:{kind}"})
        except Exception as exc:
            logger.debug("could not read browser targets: %s", exc)
        return frames

    async def _ensure_attached(self, target) -> bool:
        """Make sure ``target`` has a live CDP session.

        nodriver only auto-attaches a connection whose ``session_id`` is unset.
        The widget's connection is discovered while its iframe is still on
        ``about:blank``; navigating to ``challenges.cloudflare.com`` moves it
        to another process and invalidates that session, but the id stays set
        — so the connection *looks* attached, never re-attaches, and every
        message comes back "Session with given id not found" (-32001). Probe
        it, and re-attach from scratch when the session is dead.
        """
        _, cdp = _load_nodriver()
        try:
            await target.send(cdp.runtime.evaluate(expression="1"))
            return True
        except Exception as exc:
            logger.debug("widget session is stale (%s); re-attaching", exc)
        try:
            target.session_id = None
            await target.attach()
            return True
        except Exception as exc:
            logger.debug("could not attach to the widget target: %s", exc)
            return False

    async def widget_target(self):
        """The Turnstile widget's own CDP target, attached and usable.

        Once the widget iframe navigates to ``challenges.cloudflare.com`` it
        becomes an out-of-process iframe: its own renderer, its own widget
        host, its own target. That is the whole reason input has to be aimed
        at it directly rather than at the page.
        """
        browser = self.browser
        if browser is None:
            return None
        # The widget target only appears once the iframe navigates, long after
        # startup — so refresh rather than trusting the list we first saw.
        with contextlib.suppress(Exception):
            await browser.update_targets()
        try:
            for target in getattr(browser, "targets", None) or []:
                url = str(getattr(target, "url", "") or "")
                if "challenges.cloudflare.com" not in url:
                    continue
                return target if await self._ensure_attached(target) else None
        except Exception as exc:
            logger.debug("could not enumerate targets: %s", exc)
        return None

    async def widget_text(self) -> str | None:
        """What the Turnstile widget is displaying, read from its own frame.

        The difference between guessing at a spinner and knowing whether it
        says "Verifying…", "Failure!", or an error code — none of which is
        reachable from the parent page, whose own text only ever says
        "Waiting for verification".
        """
        target = await self.widget_target()
        if target is None:
            return None
        try:
            text = await target.evaluate(
                "(document.body ? document.body.innerText : '')"
                ".replace(/\\s+/g, ' ').trim().slice(0, 200)"
            )
        except Exception as exc:
            logger.debug("could not read the widget frame: %s", exc)
            return None
        return text.strip() if isinstance(text, str) and text.strip() else None

    async def click_widget_frame(self) -> bool:
        """Click the checkbox inside the widget's own frame.

        This is the one that actually works when the widget is an OOPIF.
        ``Input.dispatchMouseEvent`` on the page target is delivered to the
        main frame's render widget and is *not* hit-tested into a child
        frame's separate renderer, so a click aimed at the right screen
        coordinates still never reaches the checkbox — the aim is right and
        the event goes nowhere. Aiming at the widget's own target, in that
        frame's own coordinate space, puts the event where it belongs.
        """
        target = await self.widget_target()
        if target is None:
            return False

        try:
            raw = await target.evaluate("""
                JSON.stringify((() => {
                    const el = document.querySelector('input[type="checkbox"]')
                            || document.querySelector('[role="checkbox"]')
                            || document.querySelector('label');
                    if (!el) return null;
                    const r = el.getBoundingClientRect();
                    if (!r.width || !r.height) return null;
                    return {x: r.x + r.width / 2, y: r.y + r.height / 2, tag: el.tagName};
                })())
            """)
        except Exception as exc:
            logger.debug("could not locate the checkbox in the widget frame: %s", exc)
            raw = None

        spot = None
        if raw and raw != "null":
            with contextlib.suppress(ValueError, TypeError):
                spot = json.loads(raw)
        if spot is None:
            # Turnstile's checkbox sits at a stable offset inside the widget;
            # use it rather than giving up when the DOM lookup comes back empty.
            spot = {"x": 21, "y": 33, "tag": "(default position)"}

        x = spot["x"] + random.uniform(-2, 2)
        y = spot["y"] + random.uniform(-2, 2)
        try:
            await self._humanized_approach(target, x, y)
            await target.mouse_click(x, y)
        except Exception as exc:
            logger.warning("could not click inside the widget frame: %s", exc)
            return False

        logger.info(
            "clicked %s at %.0f,%.0f in widget frame %s",
            spot["tag"], x, y, str(getattr(target, "url", ""))[-60:],
        )
        return True

    async def _humanized_approach(self, target, x: float, y: float) -> None:
        """Move the pointer to ``(x, y)`` along a plausible path.

        Two mouse events either side of a pause is enough to *operate* a
        checkbox — the self-test passes on it — but a live Turnstile scores
        the pointer track leading up to the click, and two points in a
        straight line is not a track a hand produces. This walks a curved
        path with eased, jittery steps and a small overshoot-and-settle,
        which is roughly what a real approach looks like.
        """
        steps = random.randint(14, 22)
        # Start somewhere plausible: off to one side and above, as if arriving
        # from elsewhere on the page.
        start_x = x + random.uniform(-160, -60)
        start_y = y + random.uniform(-90, -30)
        # A control point off the straight line makes the path curve.
        bend_x = (start_x + x) / 2 + random.uniform(-40, 40)
        bend_y = (start_y + y) / 2 + random.uniform(-40, 40)

        for step in range(1, steps + 1):
            t = step / steps
            # Ease-out: fast at first, slowing into the target, like a hand.
            t = 1 - (1 - t) ** 2
            inv = 1 - t
            px = inv * inv * start_x + 2 * inv * t * bend_x + t * t * x
            py = inv * inv * start_y + 2 * inv * t * bend_y + t * t * y
            if step < steps:  # no jitter on the final landing point
                px += random.uniform(-1.2, 1.2)
                py += random.uniform(-1.2, 1.2)
            await target.mouse_move(px, py)
            await asyncio.sleep(random.uniform(0.008, 0.03))

        # Overshoot slightly, then settle — hands rarely stop dead on target.
        if random.random() < 0.6:
            await target.mouse_move(x + random.uniform(1, 4), y + random.uniform(-3, 3))
            await asyncio.sleep(random.uniform(0.03, 0.08))
            await target.mouse_move(x, y)
        await asyncio.sleep(random.uniform(0.06, 0.16))

    async def press_key(
        self, key: str, code: str, vk: int, text: str | None = None, target=None
    ) -> None:
        """Send a key. ``target`` defaults to the page — pass the widget's own
        target to reach a control inside an out-of-process frame, for the same
        routing reason clicks need it."""
        _, cdp = _load_nodriver()
        destination = target or self.page
        for event_type in ("keyDown", "keyUp"):
            with contextlib.suppress(Exception):
                await destination.send(
                    cdp.input_.dispatch_key_event(
                        type_=event_type,
                        key=key,
                        code=code,
                        windows_virtual_key_code=vk,
                        native_virtual_key_code=vk,
                        text=text if event_type == "keyDown" else None,
                    )
                )

    async def activate_by_keyboard(self) -> bool:
        """Tab to the widget and press Space.

        A second way in, for when a coordinate click doesn't take. Turnstile's
        checkbox is keyboard-accessible, and this drives it through focus
        handling rather than hit-testing — which matters because the checkbox
        lives in a cross-origin iframe inside a closed shadow root, the least
        favourable case for clicking at a point.

        Focus entering an iframe (or a shadow host) shows up as
        ``document.activeElement``, so we can tell when we've arrived.
        """
        # When the widget has its own target, focus and key the control
        # directly — tabbing from the parent page cannot cross into an
        # out-of-process frame's focus chain.
        target = await self.widget_target()
        if target is not None:
            try:
                focused = await target.evaluate("""
                    (() => {
                        const el = document.querySelector('input[type="checkbox"]')
                                || document.querySelector('[role="checkbox"]');
                        if (!el) return false;
                        el.focus();
                        return document.activeElement === el;
                    })()
                """)
                if focused:
                    await self.press_key(" ", "Space", 32, text=" ", target=target)
                    await asyncio.sleep(1.5)
                    logger.info("pressed Space on the checkbox in the widget frame")
                    return True
            except Exception as exc:
                logger.debug("could not key the widget frame: %s", exc)

        for _ in range(8):
            await self.press_key("Tab", "Tab", 9)
            await asyncio.sleep(0.15)
            focused = await self._eval("""
                (() => {
                    const el = document.activeElement;
                    if (!el) return '';
                    const box = document.querySelector('.cf-turnstile,[data-sitekey]');
                    const inside = box && (box === el || box.contains(el));
                    return (inside ? 'widget:' : '') + el.tagName;
                })()
            """)
            if focused and focused.startswith("widget:"):
                logger.info("keyboard focus reached the widget (%s)", focused)
                await self.press_key(" ", "Space", 32, text=" ")
                await asyncio.sleep(1.5)
                return True
            if focused == "IFRAME":
                logger.info("keyboard focus reached an iframe")
                await self.press_key(" ", "Space", 32, text=" ")
                await asyncio.sleep(1.5)
                return True
        logger.info("keyboard focus never reached the widget")
        return False

    async def click_checkbox(self, rect: dict | None) -> None:
        """Click the checkbox: approach from a short distance, pause, click.

        The checkbox sits ~28px from the frame's left edge; the jitter and the
        two-step move exist because an instantaneous teleport-and-click reads
        as synthetic.
        """
        if rect:
            x = rect["x"] + 28 + random.uniform(-3, 3)
            y = rect["y"] + rect["h"] / 2 + random.uniform(-3, 3)
        else:
            # Nothing found anywhere — aim at the widget we mount ourselves.
            # A blind click at fixed coordinates helps nobody else.
            logger.debug("no widget or container found; clicking the injected box")
            x = 48 + random.uniform(-3, 3)
            y = 52 + random.uniform(-3, 3)
        await self.page.mouse_move(x - 80, y - 20)
        await asyncio.sleep(random.uniform(0.15, 0.25))
        await self.page.mouse_move(x, y)
        await asyncio.sleep(random.uniform(0.08, 0.15))
        await self.page.mouse_click(x, y)

    # -- the attempt loop --------------------------------------------------

    async def attempt(self) -> str | None:
        """One attempt: click and poll until a token/grant appears or time runs out."""
        config = self.config
        token = await self.get_token()
        if token:
            return token
        if await self.refresh_grant():
            return None  # grant already in hand; caller checks self.grant

        # wait_for_widget() already gave the page its time; this is just a
        # short grace for a widget that re-renders itself. Falls back to the
        # page's own container, so a widget we can't see is still clickable.
        rect = None
        for _ in range(6):
            rect = await self.click_target()
            if rect:
                break
            await asyncio.sleep(0.5)
        if rect:
            logger.info(
                "clicking the %s at %dx%d+%d+%d",
                rect.get("source", "widget"),
                round(rect["w"]), round(rect["h"]), round(rect["x"]), round(rect["y"]),
            )

        deadline = time.monotonic() + config.attempt_timeout
        clicks = 0
        last_click = 0.0
        keyboard_tried = False

        # Watch before touching anything. A Turnstile widget in managed mode
        # verifies on its own and only falls back to a checkbox if it wants
        # one; while it is working it shows a spinner, and clicking a spinner
        # achieves nothing at best. Interrupting its own run is the more
        # likely outcome, so give it a clear window first.
        if config.pre_click_wait > 0:
            watch_until = min(deadline, time.monotonic() + config.pre_click_wait)
            while time.monotonic() < watch_until:
                token = await self.get_token()
                if token:
                    logger.info("widget solved itself, no interaction needed")
                    return token
                if await self.refresh_grant():
                    return None
                await asyncio.sleep(0.5)
            logger.info(
                "widget still unsolved after %.0fs of watching (it says %r); clicking",
                config.pre_click_wait, await self.widget_text(),
            )

        while time.monotonic() < deadline:
            token = await self.get_token()
            if token:
                return token
            if await self.refresh_grant():
                return None

            now = time.monotonic()
            if clicks == 0 or now - last_click > config.click_interval:
                if clicks >= config.max_clicks:
                    await asyncio.sleep(0.3)
                    continue
                # Prefer the widget's own frame; only fall back to a page-level
                # click when it has no target of its own (same-process iframe,
                # or a widget we mounted ourselves).
                if not await self.click_widget_frame():
                    await self.click_checkbox(rect)
                last_click = time.monotonic()
                clicks += 1
                await asyncio.sleep(1.5)
                # The widget goes to "Verifying…" here; say so, because a
                # widget that verifies but never returns a token is a very
                # different problem from one that ignores the click.
                state = await self.widget_present()
                logger.info(
                    "after click %d: widget present=%s solved=%s hit=%s says=%r",
                    clicks, state.get("present"), state.get("solved"),
                    await self.element_at(rect), await self.widget_text(),
                )
                # A widget always reacts visibly to a click it received — the
                # checkbox becomes a spinner. Capturing the moment after the
                # click is the only way to tell "Cloudflare is stalling us"
                # from "the click never arrived", which look identical later.
                await self.dump_artifacts(f"after-click-{clicks}")
                # A click that lands on the right element and still does
                # nothing may just be the wrong kind of input for a checkbox
                # buried in a cross-origin frame. Try the keyboard once.
                if not state.get("solved") and not keyboard_tried:
                    keyboard_tried = True
                    await self.activate_by_keyboard()
                rect = await self.click_target() or rect
                continue

            await asyncio.sleep(0.3)

        return None

    async def run(self) -> SolveResult:
        config = self.config
        started = time.monotonic()
        token: str | None = None
        attempts = 0

        for attempt in range(1, max(1, config.attempts) + 1):
            attempts = attempt
            await self.open_page()
            if await self.wait_for_widget():
                if attempt == 1:
                    # Whether Turnstile's iframe actually loaded is the single
                    # most useful fact once a widget is on the page.
                    logger.info("frames in the page: %s", await self.cdp_frames())
            else:
                self.last_diagnostics = await self.log_missing_widget()
                await self.force_widget()
                # Short grace for the widget we just forced — an explicit
                # render either lands in a couple of seconds or not at all.
                await self.wait_for_widget(5.0)

            token = await self.attempt()
            if token or self.grant:
                break
            if attempt < config.attempts:
                logger.debug("attempt %d/%d failed, retrying", attempt, config.attempts)
                await asyncio.sleep(config.retry_delay)

        if not (token or self.grant):
            self.last_diagnostics = await self.diagnostics()
            await self.dump_artifacts()

        if (token or self.grant) and config.hold_open > 0:
            # The page may still be POSTing the token to its own backend.
            await asyncio.sleep(config.hold_open)
            with contextlib.suppress(Exception):
                await self.refresh_grant()

        return SolveResult(
            token=token,
            grant=self.grant,
            attempts=attempts,
            elapsed=time.monotonic() - started,
            headless=self.headless,
            diagnostics=self.last_diagnostics,
        )


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------

_cache: dict[tuple[str, str], tuple[float, str]] = {}


class TurnstileSolver:
    """Reusable solver bound to a :class:`~turnstile_solver.SolverConfig`.

    Cheap to construct and safe to keep around; each solve launches and tears
    down its own browser, so instances hold no OS resources between calls.

        >>> solver = TurnstileSolver(SolverConfig(attempts=5))
        >>> result = solver.solve("https://example.com/challenge")
        >>> result.token
        '0.abc...'
    """

    def __init__(self, config: SolverConfig | None = None) -> None:
        self.config = config or DEFAULT_CONFIG

    def _config_for(self, overrides: dict) -> SolverConfig:
        return replace(self.config, **overrides) if overrides else self.config

    async def solve_async(
        self,
        url: str,
        *,
        sitekey: str | None = None,
        **overrides,
    ) -> SolveResult:
        """Solve the challenge at ``url``.

        ``sitekey`` is only consulted for the injection fallback; leave it
        ``None`` and it is scraped from the page if and when that fallback is
        reached. Any :class:`~turnstile_solver.SolverConfig` field may be
        passed as a keyword to override it for this call.

        Raises :class:`~turnstile_solver.errors.SolveTimeout` when every
        attempt came back empty, and
        :class:`~turnstile_solver.errors.BrowserNotFoundError` /
        :class:`~turnstile_solver.errors.BrowserUnavailableError` when there
        is no usable browser.
        """
        config = self._config_for(overrides)

        cache_key = (sitekey or "", url)
        if self._cacheable(config):
            cached = self._cache_get(cache_key, config.cache_ttl)
            if cached:
                return SolveResult(token=cached, cached=True)

        if sitekey is None:
            # Cheap and off the event loop; only ever used if we must inject.
            sitekey = await asyncio.to_thread(discover_sitekey, url)

        async with _Session(url, sitekey, config) as session:
            result = await session.run()

        if not result:
            raise SolveTimeout(
                f"no token or grant after {result.attempts} attempt(s) "
                f"({result.elapsed:.0f}s) at {url} — {_explain(result.diagnostics)}"
            )
        if self._cacheable(config) and result.token:
            _cache[cache_key] = (time.time(), result.token)
        return result

    def solve(self, url: str, *, sitekey: str | None = None, **overrides) -> SolveResult:
        """Blocking :meth:`solve_async`.

        Refuses to run inside a live event loop, where it would block the loop
        for the whole solve — ``await solve_async(...)`` there, or hand this
        method to ``asyncio.to_thread``.
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise RuntimeError(
                "TurnstileSolver.solve() cannot run inside an event loop; "
                "use `await solver.solve_async(...)` instead"
            )
        return asyncio.run(self.solve_async(url, sitekey=sitekey, **overrides))

    # -- cache -------------------------------------------------------------

    @staticmethod
    def _cacheable(config: SolverConfig) -> bool:
        # A cached token replays nothing: no page load, so no grant and none
        # of the background work `hold_open` exists to wait for.
        return config.cache_ttl > 0 and not config.capture_grant and config.hold_open <= 0

    @staticmethod
    def _cache_get(key: tuple[str, str], ttl: float) -> str | None:
        entry = _cache.get(key)
        if entry is None:
            return None
        stored_at, token = entry
        if time.time() - stored_at <= ttl:
            return token
        _cache.pop(key, None)
        return None


def clear_cache() -> None:
    """Drop every cached token (process-wide, shared by all solvers)."""
    _cache.clear()


_default_solver = TurnstileSolver()


def solve(url: str, *, sitekey: str | None = None, **overrides) -> SolveResult:
    """Blocking one-shot solve using the default configuration."""
    return _default_solver.solve(url, sitekey=sitekey, **overrides)


async def solve_async(url: str, *, sitekey: str | None = None, **overrides) -> SolveResult:
    """Async one-shot solve using the default configuration."""
    return await _default_solver.solve_async(url, sitekey=sitekey, **overrides)
