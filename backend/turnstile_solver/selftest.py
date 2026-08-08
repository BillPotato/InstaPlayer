"""``python -m turnstile_solver.selftest`` — can this machine solve a Turnstile?

Answers that in seconds against a page we host ourselves, using Cloudflare's
official test sitekeys, instead of minutes against a real challenge. That makes
it usable as a development loop *and* as a deployment check: if the self-test
can't tick a checkbox here, no real challenge will work either.

The test keys behave predictably and are not domain-locked, so a page served
from loopback is fine:

===========================  ==========================================
``1x00000000000000000000AA``  always passes, no interaction
``3x00000000000000000000FF``  forces the interactive checkbox  (default)
``2x00000000000000000000AB``  always blocks
===========================  ==========================================

``--dump`` prints the widget frame's own DOM, which is otherwise very hard to
get at — it lives in a cross-origin out-of-process iframe.
"""
from __future__ import annotations

import argparse
import contextlib  # noqa: F401 - used by _dump
import functools
import http.server
import json
import logging
import socket
import sys
import threading

logger = logging.getLogger("selftest")

#: Cloudflare's documented test keys.
SITEKEY_PASS = "1x00000000000000000000AA"
SITEKEY_INTERACTIVE = "3x00000000000000000000FF"
SITEKEY_BLOCK = "2x00000000000000000000AB"

_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Turnstile self-test</title>
<script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async defer></script>
</head><body style="font:14px sans-serif;padding:40px">
<h1>Turnstile self-test</h1>
<p>Sitekey: __SITEKEY__</p>
<div class="cf-turnstile" data-sitekey="__SITEKEY__" data-callback="verified"></div>
<script>function verified(t) { window._selftestToken = t; }</script>
</body></html>
"""


class _Handler(http.server.BaseHTTPRequestHandler):
    def __init__(self, *args, sitekey: str = SITEKEY_INTERACTIVE, **kwargs):
        self.sitekey = sitekey
        super().__init__(*args, **kwargs)

    def do_GET(self) -> None:
        body = _PAGE.replace("__SITEKEY__", self.sitekey).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args) -> None:
        pass


def serve(sitekey: str) -> tuple[str, http.server.HTTPServer]:
    """Serve the test page on a free loopback port."""
    server = http.server.HTTPServer(
        ("127.0.0.1", 0), functools.partial(_Handler, sitekey=sitekey)
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_address[1]}/", server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m turnstile_solver.selftest")
    parser.add_argument(
        "--sitekey",
        default=SITEKEY_INTERACTIVE,
        help="test key, or 'pass' / 'interactive' / 'block'",
    )
    parser.add_argument("--dump", action="store_true", help="print the widget frame's DOM")
    parser.add_argument(
        "--fingerprint",
        action="store_true",
        help="report the signals anti-bot scripts read from this browser",
    )
    parser.add_argument("--show-window", action="store_true")
    parser.add_argument(
        "--proxy", help="route the browser through scheme://[user:pass@]host:port"
    )
    parser.add_argument("--attempts", type=int, default=1)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    sitekey = {
        "pass": SITEKEY_PASS,
        "interactive": SITEKEY_INTERACTIVE,
        "block": SITEKEY_BLOCK,
    }.get(args.sitekey, args.sitekey)

    from .config import SolverConfig
    from .errors import SolverError
    from .solver import TurnstileSolver

    url, server = serve(sitekey)
    logger.info("serving the test page at %s with sitekey %s", url, sitekey)

    config = SolverConfig(
        capture_grant=False,  # nothing issues a grant here; we want the token
        offscreen=not args.show_window,
        attempts=args.attempts,
        proxy=args.proxy,
    )

    if args.fingerprint:
        return _fingerprint(url, config, server)

    if args.dump:
        return _dump(url, config, server)

    try:
        result = TurnstileSolver(config).solve(url)
    except SolverError as exc:
        logger.error("SELF-TEST FAILED: %s", exc)
        return 1
    finally:
        server.shutdown()

    logger.info("SELF-TEST PASSED in %.0fs — token %s…", result.elapsed, (result.token or "")[:24])
    return 0


_JS_FINGERPRINT = """
    JSON.stringify((() => {
        const out = {};
        const nav = navigator;
        out.webdriver = nav.webdriver;
        out.userAgent = nav.userAgent;
        out.platform = nav.platform;
        out.languages = nav.languages;
        out.hardwareConcurrency = nav.hardwareConcurrency;
        out.deviceMemory = nav.deviceMemory;
        out.plugins = nav.plugins ? nav.plugins.length : null;
        out.mimeTypes = nav.mimeTypes ? nav.mimeTypes.length : null;
        out.hasChromeObject = typeof window.chrome === 'object';
        out.screen = [screen.width, screen.height, screen.colorDepth,
                      window.devicePixelRatio];
        out.timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
        out.timezoneOffsetMinutes = new Date().getTimezoneOffset();
        // The big one: software rendering announces itself here, and no real
        // visitor's machine reports a software rasteriser.
        try {
            const c = document.createElement('canvas');
            const gl = c.getContext('webgl') || c.getContext('experimental-webgl');
            if (gl) {
                const dbg = gl.getExtension('WEBGL_debug_renderer_info');
                out.webglVendor = dbg ? gl.getParameter(dbg.UNMASKED_VENDOR_WEBGL) : null;
                out.webglRenderer = dbg ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : null;
            } else {
                out.webglVendor = out.webglRenderer = '(no webgl context)';
            }
        } catch (e) { out.webglError = String(e); }
        try {
            const c = document.createElement('canvas');
            const ctx = c.getContext('2d');
            ctx.textBaseline = 'top';
            ctx.font = '14px Arial';
            ctx.fillText('fingerprint', 2, 2);
            out.canvasWorks = c.toDataURL().length > 100;
        } catch (e) { out.canvasWorks = false; }
        out.webrtc = typeof RTCPeerConnection === 'function';
        out.mediaDevices = !!(nav.mediaDevices && nav.mediaDevices.enumerateDevices);
        out.pdfViewer = nav.pdfViewerEnabled;
        out.fonts = document.fonts ? document.fonts.size : null;
        out.touchPoints = nav.maxTouchPoints;
        out.connection = nav.connection ? nav.connection.effectiveType : null;
        return out;
    })())
"""


def _egress() -> dict:
    """Where this machine's outbound traffic appears to come from.

    Makes one call to a public IP-geolocation service, so it only runs in this
    explicitly-invoked diagnostic — never on a server path. The address matters
    because a challenge scores the browser's clock against the address the
    request arrived from: on a hosting provider that is the provider's region,
    not the operator's, which is exactly the case people get wrong.
    """
    import urllib.request

    try:
        with urllib.request.urlopen("https://ipinfo.io/json", timeout=10) as response:
            data = json.loads(response.read().decode("utf-8", errors="replace"))
    except Exception as exc:
        return {"error": f"could not determine the egress address: {exc}"}
    return {
        "ip": data.get("ip"),
        "city": data.get("city"),
        "country": data.get("country"),
        "org": data.get("org"),
        "timezone": data.get("timezone"),
    }


def _fingerprint(url: str, config, server) -> int:
    """Report what an anti-bot script would read from this browser.

    Cloudflare scores the client, so when a challenge comes back
    ``failure_retry`` the useful question is which of these values looks
    unlike a real visitor's.
    """
    import asyncio

    from .solver import _Session

    async def run() -> int:
        async with _Session(url, None, config) as session:
            await session.open_page()
            await asyncio.sleep(2)
            raw = await session._eval(_JS_FINGERPRINT)
            browser = json.loads(raw) if raw else {}

            egress = _egress()
            print(json.dumps({"headless": session.headless}))
            print(json.dumps({"egress": egress}, indent=2))
            print(raw or '{"error": "no fingerprint returned"}')

            # The comparison this whole mode exists for.
            wanted, got = egress.get("timezone"), browser.get("timezone")
            if wanted and got:
                if wanted == got:
                    logger.info("timezone matches the egress address (%s)", got)
                else:
                    logger.warning(
                        "TIMEZONE MISMATCH: the browser says %s but this machine's "
                        "traffic leaves from %s. Set TZ=%s",
                        got, wanted, wanted,
                    )
            return 0

    try:
        return asyncio.run(run())
    finally:
        server.shutdown()


async def _frame_tree(session) -> list[dict]:
    """Every frame in the page, with its id — ids are what let us run code in
    a frame that has no CDP target of its own."""
    from .solver import _load_nodriver

    _, cdp = _load_nodriver()
    frames: list[dict] = []

    def walk(node, depth: int = 0) -> None:
        frame = getattr(node, "frame", None)
        if frame is not None:
            frames.append({
                "depth": depth,
                "id": str(getattr(frame, "id_", "") or getattr(frame, "id", "")),
                "url": (getattr(frame, "url", "") or "")[:100],
                "name": getattr(frame, "name", None),
            })
        for child in getattr(node, "child_frames", None) or []:
            walk(child, depth + 1)

    with contextlib.suppress(Exception):
        walk(await session.page.send(cdp.page.get_frame_tree()))
    return frames


async def _inspect_frame(session, frame_id: str) -> dict:
    """Run JS inside a frame that has no target, via an isolated world.

    ``Page.createIsolatedWorld`` hands back an execution context bound to that
    frame, which ``Runtime.evaluate`` can then use — the way to reach a frame
    that is part of the page rather than a target of its own.
    """
    from .solver import _load_nodriver

    _, cdp = _load_nodriver()
    try:
        context_id = await session.page.send(
            cdp.page.create_isolated_world(frame_id=frame_id, world_name="probe")
        )
        result = await session.page.send(
            cdp.runtime.evaluate(
                expression="""
                    JSON.stringify((() => {
                        const out = [];
                        document.querySelectorAll('body *').forEach((el) => {
                            const r = el.getBoundingClientRect();
                            if (!r.width || !r.height) return;
                            out.push({
                                tag: el.tagName,
                                id: el.id || null,
                                type: el.getAttribute('type'),
                                role: el.getAttribute('role'),
                                label: (el.getAttribute('aria-label')
                                        || (el.textContent || '').trim().slice(0, 30)) || null,
                                rect: [Math.round(r.x), Math.round(r.y),
                                       Math.round(r.width), Math.round(r.height)],
                            });
                        });
                        return {
                            url: location.href.slice(0, 80),
                            text: (document.body.innerText || '').replace(/\\s+/g, ' ').slice(0, 120),
                            elements: out.slice(0, 25),
                        };
                    })())
                """,
                context_id=context_id,
                return_by_value=True,
            )
        )
        value = getattr(result[0], "value", None) if isinstance(result, tuple) else None
        return json.loads(value) if value else {"error": "no value returned"}
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def _dump(url: str, config, server) -> int:
    """Open the page and print the widget frame's DOM, then leave."""
    import asyncio

    from .solver import _Session

    async def run() -> int:
        async with _Session(url, None, config) as session:
            await session.open_page()
            for _ in range(40):
                await asyncio.sleep(0.5)

                # Turnstile nests frames, so list every candidate before
                # picking one — attaching to the wrong one looks identical to
                # a widget that renders nothing.
                with contextlib.suppress(Exception):
                    await session.browser.update_targets()
                candidates = [
                    t
                    for t in (getattr(session.browser, "targets", None) or [])
                    if "challenges.cloudflare.com" in str(getattr(t, "url", "") or "")
                ]
                if candidates:
                    print(json.dumps({
                        "headless": session.headless,
                        "cfTargets": [str(getattr(t, "url", ""))[:120] for t in candidates],
                    }))

                target = await session.widget_target()
                if target is None:
                    continue
                # The frame exists well before it paints; dumping on first
                # sight shows an empty body and proves nothing.
                await asyncio.sleep(6)

                # The page's own frame tree, with ids — the visible widget
                # frame lives here, not in the target list, because its URL
                # never becomes a challenges.cloudflare.com one.
                print(json.dumps({"pageFrames": await _frame_tree(session)}))
                for frame in await _frame_tree(session):
                    if not (frame.get("name") or "").startswith("cf-chl-widget"):
                        continue
                    print(json.dumps({
                        "visibleWidgetFrame": frame,
                        "contents": await _inspect_frame(session, frame["id"]),
                    }))
                # Structure, not stylesheets: the body's markup plus every
                # visible element with its rect, which is what a click needs.
                raw = await target.evaluate("""
                    JSON.stringify((() => {
                        const out = [];
                        document.querySelectorAll('body *').forEach((el) => {
                            const r = el.getBoundingClientRect();
                            if (!r.width || !r.height) return;
                            out.push({
                                tag: el.tagName,
                                id: el.id || null,
                                cls: (el.className && el.className.baseVal !== undefined
                                      ? el.className.baseVal : el.className) || null,
                                role: el.getAttribute('role'),
                                type: el.getAttribute('type'),
                                label: (el.getAttribute('aria-label')
                                        || (el.textContent || '').trim().slice(0, 40)) || null,
                                rect: [Math.round(r.x), Math.round(r.y),
                                       Math.round(r.width), Math.round(r.height)],
                            });
                        });
                        return {
                            title: document.title,
                            text: (document.body.innerText || '').replace(/\\s+/g, ' ').slice(0, 200),
                            bodyHtml: (document.body.innerHTML || '').slice(0, 1200),
                            childFrames: document.querySelectorAll('iframe').length,
                            elements: out.slice(0, 40),
                        };
                    })())
                """)
                with contextlib.suppress(Exception):
                    await session.page.save_screenshot("/data/verify-diagnostics/selftest.png")
                    print(json.dumps({"screenshot": "/data/verify-diagnostics/selftest.png"}))
                # The tail of the document, where the body markup lives — the
                # head is several KB of widget stylesheet.
                with contextlib.suppress(Exception):
                    full = await target.evaluate(
                        "document.documentElement.outerHTML.slice(-1200)"
                    )
                    print(json.dumps({"documentTail": full}))
                if raw:
                    print(raw)
                    return 0
            print(json.dumps({"error": "widget frame never appeared"}))
            return 1

    try:
        return asyncio.run(run())
    finally:
        server.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
