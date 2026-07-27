"""Best-effort discovery of a Turnstile sitekey from a challenge page.

Only needed for the *injection* fallback: when a page renders its own widget
the solver just clicks it, and the sitekey is irrelevant. Uses ``urllib`` so
the package keeps ``nodriver`` as its only third-party dependency.
"""
from __future__ import annotations

import logging
import re
import urllib.request

from .errors import SitekeyNotFound

logger = logging.getLogger(__name__)

_SITEKEY_PATTERNS = (
    re.compile(r'data-sitekey=["\']([0-9A-Za-z_-]{10,})["\']'),
    re.compile(r'["\']?sitekey["\']?\s*[:=]\s*["\']([0-9A-Za-z_-]{10,})["\']'),
    re.compile(r"sitekey=([0-9A-Za-z_-]{10,})"),
)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def sitekey_from_html(html: str) -> str | None:
    """First sitekey matched in ``html``, or ``None``."""
    for pattern in _SITEKEY_PATTERNS:
        match = pattern.search(html)
        if match:
            return match.group(1)
    return None


def discover_sitekey(
    url: str,
    *,
    timeout: float = 10.0,
    required: bool = False,
) -> str | None:
    """Fetch ``url`` and scrape a Turnstile sitekey out of the markup.

    Returns ``None`` when the page can't be fetched or exposes no sitekey —
    a page that renders the widget from JavaScript legitimately has none in
    its initial HTML. Pass ``required=True`` to get
    :class:`~turnstile_solver.errors.SitekeyNotFound` instead.
    """
    html = ""
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            html = response.read().decode(charset, errors="replace")
    except Exception as exc:  # network, TLS, HTTP error — all non-fatal here
        logger.debug("sitekey fetch failed for %s: %s", url, exc)

    sitekey = sitekey_from_html(html) if html else None
    if sitekey is None and required:
        raise SitekeyNotFound(f"no Turnstile sitekey found at {url}")
    return sitekey
