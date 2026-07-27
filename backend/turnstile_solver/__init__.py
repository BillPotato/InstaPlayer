"""Automated Cloudflare Turnstile solving, as a library.

Extracted from the SpotiFLAC desktop community-verification flow so it can be
reused independently of it. Nothing in here knows about SpotiFLAC, sessions,
or InstaPlayer — it takes a URL and gives back a token and/or a grant.

Quick start::

    from turnstile_solver import solve

    result = solve("https://example.com/challenge")
    print(result.token, result.grant)

Async (e.g. from FastAPI)::

    from turnstile_solver import solve_async

    result = await solve_async(url, capture_grant=True, hold_open=3.0)

Requires a Chromium-family browser on the host and ``pip install nodriver``.

Headless hosts (Docker, CI, a VPS) work out of the box: an Xvfb virtual
display is started automatically when one is available, and Chrome's own
headless mode is used as a fallback. See ``README.md`` next to this file for
the full guide, including a ready-made container setup.
"""
from __future__ import annotations

from .config import (
    DEFAULT_CONFIG,
    Headless,
    SolverConfig,
    default_profile_dir,
    find_browser,
    start_virtual_display,
    virtual_display_active,
)
from .errors import (
    BrowserNotFoundError,
    BrowserUnavailableError,
    DisplayUnavailableError,
    SitekeyNotFound,
    SolverError,
    SolveTimeout,
)
from .sitekey import discover_sitekey, sitekey_from_html
from .solver import (
    SolveResult,
    TurnstileSolver,
    clear_cache,
    extract_grant,
    solve,
    solve_async,
)

__version__ = "1.0.0"

__all__ = [
    "DEFAULT_CONFIG",
    "BrowserNotFoundError",
    "BrowserUnavailableError",
    "DisplayUnavailableError",
    "Headless",
    "SitekeyNotFound",
    "SolveResult",
    "SolveTimeout",
    "SolverConfig",
    "SolverError",
    "TurnstileSolver",
    "clear_cache",
    "default_profile_dir",
    "discover_sitekey",
    "extract_grant",
    "find_browser",
    "sitekey_from_html",
    "solve",
    "solve_async",
    "start_virtual_display",
    "virtual_display_active",
    "__version__",
]
