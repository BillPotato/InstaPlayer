"""Exception hierarchy for :mod:`turnstile_solver`.

Everything the package raises on purpose derives from :class:`SolverError`, so
a caller that only wants "did it work?" can wrap a single ``except``.
"""
from __future__ import annotations


class SolverError(Exception):
    """Base class for every error raised by this package."""


class BrowserNotFoundError(SolverError):
    """No Chromium-based browser could be located.

    Install Chrome/Edge/Brave/Chromium, or point ``CHROME_PATH`` (or
    ``SolverConfig.chrome_path``) at the executable.
    """


class BrowserUnavailableError(SolverError):
    """A browser was found but could not be driven (launch or CDP failure)."""


class DisplayUnavailableError(SolverError):
    """``headless=False`` was asked for on a host with no display.

    Set ``DISPLAY``, install Xvfb so one can be started, or allow the headless
    fallback with ``headless="auto"``.
    """


class SolveTimeout(SolverError):
    """Every attempt elapsed without producing a token or a grant."""


class SitekeyNotFound(SolverError):
    """The challenge page exposed no ``sitekey`` to scrape.

    Only raised by :func:`turnstile_solver.discover_sitekey` when
    ``required=True``; the solver itself treats a missing sitekey as
    non-fatal, since a page rendering its own widget doesn't need one.
    """
