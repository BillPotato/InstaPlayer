"""``python -m app.verify_cli <challenge-url>`` — what the engine runs to verify.

This sits between the engine and :mod:`turnstile_solver` because the engine's
own handoff can't be relied on.

The engine passes a challenge URL carrying ``?cb=http://127.0.0.1:PORT/session-grant?state=…``
and then waits on that loopback server for a grant, exactly as the desktop app
does. The catch, documented in the upstream mobile client
(``signed_session_mobile.py``, ``authenticate_with_turnstile``): the challenge
page calls its own ``/challenge/verify`` endpoint with its Cloudflare cookies
and acts on the JSON reply — it does **not** reliably navigate to ``cb``. Wait
for a redirect that never comes and the engine times out five minutes later
having solved the captcha perfectly.

So we take the grant from the horse's mouth. The solver already watches network
responses for it; this module hands what it finds to the engine's callback
itself. If the page *does* redirect, the engine has the grant already and our
delivery is a harmless no-op.

Grants are short-lived (the verify response says ``expires_in: 60``), so
delivery happens the moment the solve returns.
"""
from __future__ import annotations

import argparse
import logging
import sys
import urllib.error
import urllib.parse
import urllib.request

log = logging.getLogger("verify")


def callback_url(challenge_url: str) -> str | None:
    """The engine's loopback callback, taken from the challenge URL's ``cb``."""
    try:
        params = urllib.parse.parse_qs(urllib.parse.urlparse(challenge_url).query)
    except ValueError:
        return None
    candidate = (params.get("cb") or [""])[0].strip()
    if not candidate:
        return None
    # Only ever call back into the loopback HTTP server the engine started.
    # The engine overwrites any `cb` the remote service supplied with its own,
    # so this shouldn't be reachable — but the grant is a credential, and it
    # costs nothing to refuse anything that isn't plain http to localhost.
    parsed = urllib.parse.urlparse(candidate)
    if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
        log.warning("ignoring callback that is not loopback http: %r", candidate)
        return None
    return candidate


def deliver_grant(callback: str, grant: str, timeout: float = 15.0) -> bool:
    """Hand the grant to the engine. ``True`` if it accepted it.

    A refused connection normally means the engine already got the grant from
    the page's own redirect and shut the server down — success, not failure,
    which is why the caller treats delivery as best-effort.
    """
    separator = "&" if urllib.parse.urlparse(callback).query else "?"
    url = f"{callback}{separator}grant={urllib.parse.quote(grant, safe='')}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            ok = 200 <= response.status < 300
            log.info("delivered grant to the engine (HTTP %s)", response.status)
            return ok
    except urllib.error.HTTPError as exc:
        log.error("engine rejected the grant: HTTP %s %s", exc.code, exc.reason)
    except Exception as exc:
        log.info("could not reach the engine callback (%s)", exc)
    return False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.verify_cli",
        description="Solve a SpotiFLAC community-verification challenge.",
    )
    parser.add_argument(
        "url",
        nargs="?",
        help="challenge URL handed over by the engine (omit with --status/--now)",
    )
    # Operator commands. The HTTP endpoints do the same things, but a shell on
    # the server is often the only way in on a hosting platform — and the image
    # has no curl.
    parser.add_argument(
        "--status", action="store_true", help="print the community session's state"
    )
    parser.add_argument(
        "--now",
        action="store_true",
        help="mint a session now (downloads one track, which is what triggers it)",
    )
    parser.add_argument(
        "--force", action="store_true", help="with --now, discard the current session first"
    )
    parser.add_argument("--hold-open", type=float, default=5.0)
    parser.add_argument("--diagnostics-dir")
    parser.add_argument("--attempts", type=int)
    parser.add_argument("--attempt-timeout", type=float)
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def _report(settings) -> dict:
    from . import verification

    return verification.status_report(settings)


def run_status() -> int:
    """Print the session's state — present, valid, when it expires, and
    whether the solver could mint a new one."""
    import json as _json

    from .config import get_settings

    print(_json.dumps(_report(get_settings()), indent=2))
    return 0


def run_now(force: bool) -> int:
    """Mint a session without going through HTTP.

    The engine verifies lazily, when a community request needs signing, so
    there is nothing to call directly — a one-track probe is what triggers it.
    Same path the POST endpoint takes.
    """
    import asyncio

    from . import downloader, verification
    from .config import get_settings

    settings = get_settings()
    before = _report(settings)
    if before["sessionValid"] and not force:
        log.info("session already valid until %s (use --force to replace)",
                 before["expiresAt"])
        return 0
    if not before["solverReady"]:
        log.error("the solver cannot run here: %s", before["solverError"])
        return 1

    if force:
        verification.clear_session()
    log.info("verifying — this downloads one track and takes a minute or two")
    probe = asyncio.run(downloader.probe(settings))

    after = _report(settings)
    if after["sessionValid"]:
        log.info("session valid until %s", after["expiresAt"])
        return 0
    log.error("no session was minted. probe: %s", (probe.get("detail") or "")[:160])
    log.error("diagnostics from the failed solve are under the data dir "
              "(verify-diagnostics/), newest last")
    return 1


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    if args.status:
        return run_status()
    if args.now:
        return run_now(args.force)
    if not args.url:
        build_parser().error("give a challenge URL, or use --status / --now")

    from turnstile_solver import SolverConfig, SolverError, TurnstileSolver

    overrides = {
        "hold_open": args.hold_open,
        "diagnostics_dir": args.diagnostics_dir,
        "attempts": args.attempts,
        "attempt_timeout": args.attempt_timeout,
    }
    config = SolverConfig(
        **{k: v for k, v in overrides.items() if v is not None},
        # Only a real `grant` counts here. The library also accepts "token"
        # and "code" for pages that name it differently, but that would let
        # any JSON the browser happens to see carry a value we then hand to
        # the engine, which forwards it to the verification service.
        grant_keys=("grant",),
    )

    callback = callback_url(args.url)
    if callback is None:
        log.warning("challenge URL carries no cb= callback; the engine can only "
                    "receive the grant if the page redirects on its own")

    try:
        result = TurnstileSolver(config).solve(args.url)
    except SolverError as exc:
        log.error("verification failed: %s", exc)
        return 1

    if not result.grant:
        # A token without a grant means the captcha passed but the page never
        # produced the credential the engine needs.
        log.error(
            "captcha passed (token=%s) but no grant was captured after %ds",
            "yes" if result.token else "no",
            round(result.elapsed),
        )
        return 1

    log.info("captured grant in %ds (%d attempt(s))", round(result.elapsed), result.attempts)
    if callback:
        deliver_grant(callback, result.grant)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
