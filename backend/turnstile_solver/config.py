"""Tuning knobs and host/browser discovery for :mod:`turnstile_solver`.

:class:`SolverConfig` is a frozen dataclass, so per-call overrides are just
``dataclasses.replace`` — see :meth:`turnstile_solver.TurnstileSolver.solve`,
which accepts the same field names as keyword arguments.

Defaults are read from the environment at *call* time rather than baked in at
import time, so a caller that sets ``CHROME_PATH`` late still gets picked up.
"""
from __future__ import annotations

import atexit
import contextlib
import logging
import os
import platform
import shutil
import subprocess
import threading
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .errors import BrowserNotFoundError, DisplayUnavailableError

logger = logging.getLogger(__name__)

#: ``headless`` values. ``"auto"`` decides per host — see
#: :meth:`SolverConfig.resolve_headless`.
Headless = Literal["auto", True, False]

#: Env vars checked, in order, for an explicit browser executable.
BROWSER_PATH_ENV_VARS = ("CHROME_PATH", "BRAVE_PATH")

#: Executables looked up on ``PATH`` when no standard install location matched.
BROWSER_COMMANDS = (
    "google-chrome",
    "chrome",
    "chromium",
    "chromium-browser",
    "msedge",
    "brave",
)

_BROWSER_CANDIDATES: dict[str, tuple[str, ...]] = {
    "Windows": (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
    ),
    "Darwin": (
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        "/Applications/Arc.app/Contents/MacOS/Arc",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ),
    "Linux": (
        "/usr/bin/google-chrome-stable",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
        "/usr/bin/brave-browser",
        "/usr/bin/microsoft-edge-stable",
    ),
}


def find_browser(explicit: str | None = None) -> str:
    """Absolute path to a Chromium-family browser.

    Resolution order: ``explicit`` → :data:`BROWSER_PATH_ENV_VARS` → the
    per-OS install locations → :data:`BROWSER_COMMANDS` on ``PATH``.

    Raises :class:`~turnstile_solver.errors.BrowserNotFoundError` if nothing
    matched. An ``explicit`` path (or one from the environment) is returned
    as given without an existence check, so a typo surfaces as a launch
    failure rather than a silent fallback to some other browser.
    """
    if explicit:
        return explicit
    for var in BROWSER_PATH_ENV_VARS:
        value = os.environ.get(var)
        if value:
            return value

    for candidate in _BROWSER_CANDIDATES.get(platform.system(), ()):
        path = os.path.expandvars(candidate)
        if os.path.exists(path):
            return path

    for command in BROWSER_COMMANDS:
        path = shutil.which(command)
        if path:
            return path

    raise BrowserNotFoundError(
        "no Chromium-based browser (Chrome, Edge, Brave, Chromium) found; "
        "install one or set CHROME_PATH / SolverConfig.chrome_path"
    )


def default_profile_dir() -> str:
    """Persistent Chrome profile directory used when none is configured.

    A *persistent* profile is deliberate: Cloudflare's clearance cookie lives
    there, so a second solve against the same host is often instant (or needs
    no interaction at all).
    """
    override = os.environ.get("TS_PROFILE_DIR")
    if override:
        return override
    if platform.system() == "Windows":
        base = os.environ.get("TEMP") or os.environ.get("TMP") or r"C:\Temp"
        return os.path.join(base, "ts_profile")
    return "/tmp/ts_profile"


_xvfb_lock = threading.Lock()
_xvfb_process: subprocess.Popen | None = None
#: True once we're driving a virtual display — whether this process started it
#: or adopted one another process left running. Kept separate from
#: ``_xvfb_process`` because the adopting process owns no process handle, and
#: getting this wrong parks the window off-screen on a screen with no window
#: manager, which is how you end up with a renderer that never paints.
_on_virtual_display = False


def _terminate_xvfb() -> None:
    global _xvfb_process
    process, _xvfb_process = _xvfb_process, None
    if process is None or process.poll() is not None:
        return
    process.terminate()
    with contextlib.suppress(subprocess.TimeoutExpired):
        process.wait(timeout=3)


def _display_socket_exists(display: str) -> bool:
    """Is an X server already listening on ``display``?

    Its socket is ``/tmp/.X11-unix/X<n>``, so this is a cheap, dependency-free
    way to tell "someone beat us to it" from "Xvfb is broken".
    """
    number = display.lstrip(":").split(".")[0]
    return number.isdigit() and os.path.exists(f"/tmp/.X11-unix/X{number}")


def start_virtual_display(
    display: str = ":99",
    screen: str = "1280x900x24",
    binary: str = "Xvfb",
) -> bool:
    """Start an Xvfb virtual display and point ``DISPLAY`` at it.

    This is the *preferred* way to run on a headless host: a real browser on a
    fake screen passes Turnstile far more often than one in headless mode,
    which Chrome advertises through several fingerprintable tells.

    Returns ``True`` if a usable ``DISPLAY`` is now set — including the case
    where one already was — and ``False`` if Xvfb is unavailable or died on
    startup, which leaves the caller free to fall back to headless. Never
    raises. Idempotent, thread-safe, and the display is torn down at exit.
    """
    global _xvfb_process, _on_virtual_display
    if os.environ.get("DISPLAY"):
        return True
    if platform.system() != "Linux":
        return False  # Xvfb is an X11 thing; Windows/macOS always have a display

    with _xvfb_lock:
        if os.environ.get("DISPLAY"):
            return True
        if _xvfb_process is not None and _xvfb_process.poll() is None:
            return True

        path = shutil.which(binary)
        if path is None:
            logger.debug("%s not on PATH; cannot start a virtual display", binary)
            return False

        try:
            process = subprocess.Popen(
                [path, display, "-screen", "0", screen, "-nolisten", "tcp"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            logger.debug("failed to start %s: %s", binary, exc)
            return False

        # Give the server a moment to bind its socket, then make sure it
        # didn't exit immediately (bad screen spec, or the display is already
        # in use).
        time.sleep(0.5)
        if process.poll() is not None:
            # "Already in use" means a usable display is right there — another
            # solver process left one running. Adopt it rather than silently
            # dropping to headless, which is a much worse browser to be.
            if _display_socket_exists(display):
                global _on_virtual_display
                os.environ["DISPLAY"] = display
                _on_virtual_display = True
                logger.debug("%s is already running on %s; using it", binary, display)
                return True
            logger.debug("%s exited immediately (code %s)", binary, process.returncode)
            return False

        _xvfb_process = process
        _on_virtual_display = True
        atexit.register(_terminate_xvfb)
        os.environ["DISPLAY"] = display
        logger.debug("started %s on %s (%s)", binary, display, screen)
        return True


#: Chrome's single-instance markers. Left behind when a browser is killed
#: rather than closed — which is what happens every time a container stops
#: mid-solve.
_SINGLETON_FILES = ("SingletonLock", "SingletonCookie", "SingletonSocket")


def clear_stale_profile_locks(profile_dir: str) -> None:
    """Remove Chrome's singleton markers from a profile before launching.

    A profile on a persistent volume regularly outlives the browser that owned
    it. Chrome then sees the lock, tries to hand the URL to an instance that no
    longer exists, and the tab we were promised never materialises — the CDP
    session goes missing mid-navigation.

    Safe because a solve owns its profile for the length of the run; running
    two solves against one ``profile_dir`` is unsupported either way (Chrome
    locks it, which is the very thing these files do).
    """
    directory = Path(profile_dir)
    if not directory.is_dir():
        return  # first run: nothing to clean
    for name in _SINGLETON_FILES:
        marker = directory / name
        try:
            # is_symlink() first: these are usually dangling symlinks, and
            # exists() follows the link and reports False for those.
            if marker.is_symlink() or marker.exists():
                marker.unlink()
                logger.debug("removed stale %s from %s", name, profile_dir)
        except OSError as exc:
            logger.debug("could not remove %s: %s", marker, exc)


def virtual_display_active() -> bool:
    """Are we driving a virtual display — started here or adopted?"""
    if _on_virtual_display:
        return True
    return _xvfb_process is not None and _xvfb_process.poll() is None


def _in_container() -> bool:
    """Rough "are we in Docker/Podman?" check, used only to pick Chrome flags."""
    if os.path.exists("/.dockerenv"):
        return True
    try:
        with open("/proc/1/cgroup", encoding="utf-8") as handle:
            return any(("docker" in line or "containerd" in line) for line in handle)
    except OSError:
        return False


def _sandbox_flags() -> tuple[str, ...]:
    """Flags a container needs and a desktop doesn't.

    Chrome refuses to run as root with its sandbox on (the usual container
    case), and the default 64 MB ``/dev/shm`` a container gets is small enough
    to crash renderers, so shared memory goes to ``/tmp`` instead.
    """
    is_root = os.name != "nt" and hasattr(os, "geteuid") and os.geteuid() == 0
    if is_root or _in_container():
        return ("--no-sandbox", "--disable-dev-shm-usage")
    return ()


@dataclass(frozen=True)
class SolverConfig:
    """Everything tunable about a solve. All fields have working defaults.

    Timing note: the overall wall-clock budget is roughly
    ``attempts * attempt_timeout + (attempts - 1) * retry_delay``, plus up to
    ``widget_wait`` per attempt spent waiting for the widget to appear.
    """

    #: Browser executable. ``None`` → :func:`find_browser`.
    chrome_path: str | None = None
    #: Chrome ``--user-data-dir``. ``None`` → :func:`default_profile_dir`.
    profile_dir: str | None = None
    #: Move the window far off-screen instead of showing it. Turnstile
    #: distrusts ``--headless``, so this is how the browser stays out of the
    #: user's way while remaining headful. Ignored when actually headless, and
    #: on an Xvfb display we started (nobody to hide from there).
    offscreen: bool = True
    #: Extra Chrome command-line flags, appended last.
    browser_args: tuple[str, ...] = ()

    #: Route the browser through a proxy: ``scheme://[user:pass@]host:port``.
    #: The point is the exit address — a challenge scores the client, and a
    #: datacentre address is refused where a residential one passes. Only the
    #: browser uses this; the engine's downloads stay on the direct path,
    #: which matters when the proxy is billed by traffic.
    #:
    #: Use a *sticky* session if the provider offers one. A solve is several
    #: round trips and they must all come from the same address.
    proxy: str | None = None

    #: Hosts the browser reaches directly, never through the proxy. Loopback
    #: has to be here: the engine's verification callback lives on 127.0.0.1,
    #: and so does the self-test's own page.
    proxy_bypass: str = "127.0.0.1,localhost,[::1],<local>"

    #: Flags to strip from the driver's own defaults, matched by prefix.
    #:
    #: ``nodriver`` disables site isolation by default, which suits most
    #: scraping but not this: Turnstile's widget *is* a cross-origin iframe,
    #: and its handshake with the parent page is built on those origins being
    #: kept apart. Chromium resolves a feature named in both ``--enable-
    #: features`` and ``--disable-features`` in favour of *disable*, so the
    #: flag has to be removed rather than countered.
    drop_browser_args: tuple[str, ...] = (
        "--disable-features=IsolateOrigins,site-per-process",
    )

    #: ``"auto"`` (default), ``True`` or ``False``. See
    #: :meth:`resolve_headless` for what ``"auto"`` decides, and prefer
    #: leaving it alone — real headless is the last-resort mode.
    headless: Headless = "auto"
    #: Allow starting an Xvfb virtual display on a headless Linux host.
    #: Setting this ``False`` on such a host forces the headless fallback.
    use_xvfb: bool = True
    #: ``DISPLAY`` value for the Xvfb server we start.
    xvfb_display: str = ":99"
    #: Xvfb screen geometry, ``<width>x<height>x<depth>``. A common panel size
    #: on purpose — ``screen.width``/``height`` are read by fingerprinters, and
    #: an unusual resolution is a small mark against you for no benefit.
    xvfb_screen: str = "1920x1080x24"
    #: Xvfb executable name or path.
    xvfb_binary: str = "Xvfb"

    #: How many times to reload the page and start over. Deliberately low: a
    #: widget that accepted the click and is verifying wants patience, not a
    #: reload, and repeatedly reloading a challenge looks worse than waiting.
    #: One retry is worth having, though — a transient failure otherwise
    #: blocks downloads until something asks again.
    attempts: int = 2
    #: Seconds to keep clicking/polling within a single attempt. A checkbox
    #: click puts the widget into "Verifying…" for several seconds before the
    #: token lands, so this needs headroom well past the click itself — and
    #: Cloudflare takes noticeably longer over a client it isn't sure about.
    attempt_timeout: float = 45.0
    #: Seconds to wait between a failed attempt and the next one.
    retry_delay: float = 5.0
    #: Seconds to wait for the page's own Turnstile widget before forcing one.
    #: Pages often hold it behind a countdown (SpotiFLAC's runs ~5s) and a cold
    #: browser in a container is slower still, so this is generous on purpose.
    widget_wait: float = 20.0
    #: Seconds to simply watch the widget before touching it. In managed mode
    #: Turnstile verifies unprompted and only shows a checkbox if it wants
    #: one, so the first move should be to let it work.
    pre_click_wait: float = 15.0
    #: Most checkbox clicks per attempt. Kept low deliberately: clicking a
    #: widget that is already verifying can knock it back to the start.
    max_clicks: int = 2
    #: Seconds to wait for a token after a click before clicking again.
    click_interval: float = 12.0
    #: Seconds to leave the tab open after success — lets a page finish the
    #: background request it fires once the challenge passes.
    hold_open: float = 0.0

    #: Watch network traffic and the address bar for a grant/token handed back
    #: by the challenge page. Turn off for a plain "just give me the token".
    capture_grant: bool = True
    #: JSON keys / query parameters treated as a grant, in priority order.
    grant_keys: tuple[str, ...] = ("grant", "token", "code")

    #: Capture page console output. Costs realism: it needs CDP's Runtime
    #: domain, whose presence a page can detect. Turn on to debug, not to pass.
    capture_console: bool = False

    #: Directory to write a screenshot, the DOM and a diagnostics JSON to when
    #: a solve fails. ``None`` disables it. Invaluable on a headless host,
    #: where the page is otherwise completely unobservable.
    diagnostics_dir: str | None = None

    #: Seconds a token stays in the process-wide cache. ``0`` disables it.
    #: Never used when ``capture_grant`` or ``hold_open`` is set — those want
    #: live side effects, which a cached token would skip.
    cache_ttl: float = 900.0

    def proxy_parts(self) -> tuple[str, str | None, str | None]:
        """Split ``proxy`` into (server, username, password).

        Chrome's ``--proxy-server`` takes no credentials, so they have to come
        out of the URL and go back in over CDP when the proxy asks for them.
        Returns ``("", None, None)`` when no proxy is configured.
        """
        if not self.proxy:
            return "", None, None
        parsed = urllib.parse.urlparse(self.proxy)
        if not parsed.hostname:
            # Tolerate a bare "host:port" with no scheme.
            parsed = urllib.parse.urlparse(f"http://{self.proxy}")
        port = f":{parsed.port}" if parsed.port else ""
        server = f"{parsed.scheme or 'http'}://{parsed.hostname}{port}"
        username = urllib.parse.unquote(parsed.username) if parsed.username else None
        password = urllib.parse.unquote(parsed.password) if parsed.password else None
        return server, username, password

    def resolved_chrome_path(self) -> str:
        return find_browser(self.chrome_path)

    def resolved_profile_dir(self) -> str:
        return self.profile_dir or default_profile_dir()

    def resolve_headless(self) -> bool:
        """Decide whether Chrome runs headless, starting Xvfb if that's better.

        Called once per solve, immediately before launch — it has the side
        effect of bringing a virtual display up when one is both wanted and
        possible.

        With ``headless="auto"`` (the default), in order:

        1. ``TS_HEADLESS`` in the environment (``1``/``true``/``0``/``false``/
           ``auto``) wins, so a container can decide without touching code.
        2. A display already exists, or the host isn't Linux → headful.
        3. Headless Linux, ``use_xvfb`` on, Xvfb starts → headful on the
           virtual display. This is the good path.
        4. Otherwise → headless, with a warning: Chrome's headless mode is
           detectable and solve rates drop.

        ``headless=False`` asks for the same thing minus step 4 — if no
        display can be arranged it raises
        :class:`~turnstile_solver.errors.DisplayUnavailableError` rather than
        silently doing something less likely to work. ``headless=True`` skips
        the display machinery entirely.
        """
        requested: Headless = self.headless
        if requested == "auto":
            requested = _headless_from_env(default="auto")

        if requested is True:
            return True

        # Windows and macOS always have a display; Linux may already have one.
        if platform.system() != "Linux" or os.environ.get("DISPLAY"):
            return False

        if self.use_xvfb and start_virtual_display(
            self.xvfb_display, self.xvfb_screen, self.xvfb_binary
        ):
            return False

        if requested is False:
            raise DisplayUnavailableError(
                "headless=False needs a display: set DISPLAY, install Xvfb "
                f"(apt-get install -y xvfb) so {self.xvfb_binary} is on PATH, "
                "or allow the fallback with headless='auto'"
            )

        logger.warning(
            "no display and no usable %s — falling back to Chrome's headless "
            "mode, which Turnstile detects far more readily; install xvfb for "
            "a much better success rate",
            self.xvfb_binary,
        )
        return True

    def chrome_args(self, headless: bool = False) -> list[str]:
        args: list[str] = [
            # A first-run/restore interstitial can replace the initial tab out
            # from under nodriver, which then navigates a target that no longer
            # exists ("Session with given id not found").
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-session-crashed-bubble",
            # Chrome throttles timers and can suspend the renderer outright in
            # a window it thinks nobody is looking at — which is every window
            # on a bare Xvfb with no window manager, and any window parked
            # off-screen. Challenge pages that arm their widget on a timer (a
            # countdown, a delayed render) then never fire, and no amount of
            # waiting produces a captcha.
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            # Without a GPU, modern Chrome refuses to fall back to software
            # WebGL unless told to, and a browser reporting *no WebGL context
            # at all* is a stronger bot signal than one reporting a software
            # rasteriser: real machines essentially always have some WebGL.
            "--enable-unsafe-swiftshader",
        ]
        if headless:
            # No window to hide, and no GPU worth initialising.
            args.append("--disable-gpu")
        elif self.offscreen and not virtual_display_active():
            # Only worth hiding from an actual person. On our own Xvfb there's
            # nobody watching, and a window parked at -32000 on a screen with
            # no window manager is a good way to get a renderer that never
            # paints — which Turnstile treats as reason enough not to solve.
            args += ["--window-position=-32000,-32000", "--window-size=1920,1080"]
        elif self.offscreen:
            args.append("--window-size=1920,1080")
        server, _, _ = self.proxy_parts()
        if server:
            args += [f"--proxy-server={server}", f"--proxy-bypass-list={self.proxy_bypass}"]
        args += _sandbox_flags()
        args += self.browser_args
        return args


def _headless_from_env(default: Headless) -> Headless:
    """``TS_HEADLESS`` as a :data:`Headless` value; ``default`` if unset/junk."""
    raw = (os.environ.get("TS_HEADLESS") or "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    if raw == "auto":
        return "auto"
    if raw:
        logger.warning("ignoring unrecognised TS_HEADLESS=%r", raw)
    return default


#: Config used by the module-level convenience functions.
DEFAULT_CONFIG = SolverConfig()
