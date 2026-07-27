"""CLI front end: ``python -m turnstile_solver <url> [options]``.

Prints the token (or grant) on stdout so the result can be piped or captured
by a shell script; diagnostics go to stderr.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

from .config import SolverConfig
from .errors import SolverError
from .solver import TurnstileSolver


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m turnstile_solver",
        description="Solve a Cloudflare Turnstile challenge and print the token.",
    )
    parser.add_argument("url", help="challenge page URL")
    parser.add_argument("--sitekey", help="sitekey for the injection fallback")
    parser.add_argument("--attempts", type=int, help="page reloads before giving up")
    parser.add_argument("--attempt-timeout", type=float, help="seconds per attempt")
    parser.add_argument("--hold-open", type=float, help="seconds to wait after success")
    parser.add_argument("--chrome-path", help="browser executable to drive")
    parser.add_argument("--profile-dir", help="Chrome --user-data-dir to reuse")
    parser.add_argument(
        "--no-grant",
        action="store_true",
        help="don't watch for a grant; return the raw token only",
    )
    parser.add_argument(
        "--show-window",
        action="store_true",
        help="keep the browser on screen instead of moving it off-screen",
    )
    headless_group = parser.add_mutually_exclusive_group()
    headless_group.add_argument(
        "--headless",
        dest="headless",
        action="store_const",
        const=True,
        help="force Chrome's headless mode (detectable; prefer Xvfb)",
    )
    headless_group.add_argument(
        "--no-headless",
        dest="headless",
        action="store_const",
        const=False,
        help="require a real display; fail instead of falling back to headless",
    )
    parser.set_defaults(headless="auto")
    parser.add_argument(
        "--no-xvfb",
        action="store_true",
        help="don't start a virtual display on a headless Linux host",
    )
    parser.add_argument("--xvfb-display", help="DISPLAY for the Xvfb server (default :99)")
    parser.add_argument("--xvfb-screen", help="Xvfb geometry, e.g. 1920x1080x24")
    parser.add_argument(
        "--diagnostics-dir",
        help="on failure, write a screenshot + DOM + page state here",
    )
    parser.add_argument("--json", action="store_true", help="print the full result as JSON")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    overrides = {
        "chrome_path": args.chrome_path,
        "profile_dir": args.profile_dir,
        "attempts": args.attempts,
        "attempt_timeout": args.attempt_timeout,
        "hold_open": args.hold_open,
        "xvfb_display": args.xvfb_display,
        "xvfb_screen": args.xvfb_screen,
        "diagnostics_dir": args.diagnostics_dir,
    }
    config = SolverConfig(
        **{key: value for key, value in overrides.items() if value is not None},
        capture_grant=not args.no_grant,
        offscreen=not args.show_window,
        headless=args.headless,
        use_xvfb=not args.no_xvfb,
    )

    try:
        result = TurnstileSolver(config).solve(args.url, sitekey=args.sitekey)
    except SolverError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(
            json.dumps(
                {
                    "token": result.token,
                    "grant": result.grant,
                    "attempts": result.attempts,
                    "elapsed": round(result.elapsed, 2),
                    "cached": result.cached,
                    "headless": result.headless,
                }
            )
        )
    else:
        print(result.value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
