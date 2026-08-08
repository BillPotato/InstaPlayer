"""Community verification: giving the engine a way to pass the captcha itself.

Since SpotiFLAC v7.2.0 the community endpoints only answer HMAC-signed
requests, and the signing key comes from a session the engine mints by passing
a Cloudflare Turnstile challenge. On the desktop a human clicks the checkbox.
Headless there is nobody to click, so the engine used to fail with "browser
integration is not ready" and an admin had to copy in a
``community_session.json`` produced by the desktop app on another machine.

The engine now does the whole flow itself (see ``openVerificationURL`` in
``cmd/spotiflac-dl/main.go``): it bootstraps the challenge, starts its own
loopback callback server, and runs whatever ``SPOTIFLAC_VERIFY_CMD`` names,
passing the challenge URL as the last argument. We point that at
``turnstile_solver``. The grant, the exchange and the session file all stay on
the engine's side of the fence — this module only:

- builds that command and the environment the engine child needs,
- reports on the session file (present? valid? expiring when?),
- can clear the credentials to force a fresh verification.

Nothing here talks to the community service directly. It couldn't: the verify
endpoint is an encrypted constant inside the Go binary.
"""
from __future__ import annotations

import json
import logging
import os
import shlex
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import Settings

log = logging.getLogger(__name__)

#: Written by the engine at ``$HOME/.spotiflac/`` (``EnsureAppDir`` in the Go
#: source). The engine's ``$HOME`` is ``SPOTIFLAC_ENGINE_HOME`` when set.
SESSION_FILENAME = "community_session.json"
APP_SUBDIR = ".spotiflac"

#: Matches the engine's ``communitySessionSkew``: a session inside this window
#: of expiry is treated as already gone, so we never start a download on
#: credentials that die mid-run.
SESSION_SKEW = timedelta(minutes=5)

#: Directory to put on the child's ``PYTHONPATH`` so ``-m turnstile_solver``
#: resolves regardless of the engine's working directory. ``app/`` lives in
#: ``backend/``, which is also where the solver package lives.
_PACKAGE_ROOT = Path(__file__).resolve().parents[1]

# The solver's readiness is logged once per reason, not once per job — a
# missing browser would otherwise repeat on every download.
_warned: set[str] = set()


def _warn_once(key: str, message: str, *args) -> None:
    if key not in _warned:
        _warned.add(key)
        log.warning(message, *args)


def session_path() -> Path:
    """Where the engine keeps its community session."""
    # Late import: spotiflac_adapter imports this module for the engine env.
    from .spotiflac_adapter import engine_home

    home = engine_home() or Path.home()
    return home / APP_SUBDIR / SESSION_FILENAME


def read_session() -> dict | None:
    """Parsed session file, or ``None`` if it's missing or unreadable."""
    try:
        data = json.loads(session_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except Exception:
        log.debug("Could not read the community session file", exc_info=True)
        return None
    return data if isinstance(data, dict) else None


def _expiry(record: dict) -> datetime | None:
    """``expires_at`` as an aware datetime. The engine writes RFC3339Nano,
    whose trailing ``Z`` ``fromisoformat`` only learned to parse in 3.11."""
    raw = str(record.get("expires_at") or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def session_is_valid(record: dict | None) -> bool:
    """Mirrors the engine's ``communitySessionValid``."""
    if not record or not record.get("session_id") or not record.get("session_secret"):
        return False
    expires_at = _expiry(record)
    return expires_at is not None and (expires_at - datetime.now(timezone.utc)) > SESSION_SKEW


def clear_session() -> bool:
    """Drop the credentials, keeping ``install_id`` — the engine mints a new
    session on its next community request. Mirrors the engine's
    ``clearCommunitySessionCredentials`` (same atomic write, same 0600).

    Returns ``False`` if there was nothing to clear.
    """
    record = read_session()
    if record is None:
        return False
    for field in ("session_id", "session_secret", "expires_at"):
        record[field] = ""

    path = session_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    os.chmod(temp_path, 0o600)
    os.replace(temp_path, path)
    os.chmod(path, 0o600)
    log.info("Community session credentials cleared; the engine will re-verify")
    return True


def solver_argv(settings: Settings) -> list[str]:
    """Command the engine runs to solve a challenge, minus the URL it appends.

    ``VERIFY_COMMAND`` overrides it — a JSON array, or a command line parsed
    with :mod:`shlex`. The default runs the bundled solver under *this*
    interpreter, so it inherits the venv the backend is running in.
    """
    override = (settings.verify_command or "").strip()
    if override:
        if override.startswith("["):
            try:
                argv = json.loads(override)
            except ValueError:
                argv = []
            if isinstance(argv, list) and all(isinstance(a, str) for a in argv) and argv:
                return argv
            log.warning("VERIFY_COMMAND is not a valid JSON string array; ignoring it")
        else:
            return shlex.split(override, posix=os.name != "nt")

    argv = [
        sys.executable,
        "-m",
        # Not turnstile_solver directly: the challenge page doesn't reliably
        # redirect to the engine's callback, so verify_cli captures the grant
        # from the page's own network traffic and delivers it. See its docstring.
        "app.verify_cli",
        # The challenge page posts the token to its own backend and only then
        # redirects to the engine's callback; leaving the tab open lets that
        # finish. This is the whole reason the grant reaches the engine.
        "--hold-open",
        str(settings.verify_hold_open),
        # A failed solve leaves a screenshot + DOM here. There is no other way
        # to see what the challenge page did on a headless server.
        "--diagnostics-dir",
        str(settings.data_dir / "verify-diagnostics"),
    ]
    if (settings.verify_proxy or "").strip():
        argv += ["--proxy", settings.verify_proxy.strip()]
    return argv


def solver_ready() -> tuple[bool, str | None]:
    """Can the default solver actually run here? ``(ready, why_not)``.

    Checked up front so a missing browser is a clear message on the status
    card instead of a download that dies four minutes later.
    """
    try:
        import turnstile_solver
    except ImportError as exc:
        return False, f"turnstile_solver is not importable: {exc}"
    try:
        import nodriver  # noqa: F401 - probing availability only
    except ImportError:
        return False, "nodriver is not installed (pip install nodriver)"
    try:
        turnstile_solver.find_browser()
    except turnstile_solver.BrowserNotFoundError as exc:
        return False, f"{exc}{_browser_install_hint()}"
    except Exception as exc:  # pragma: no cover - defensive
        return False, f"browser lookup failed: {exc}"
    return True, None


def _in_container() -> bool:
    if os.path.exists("/.dockerenv"):
        return True
    try:
        with open("/proc/1/cgroup", encoding="utf-8") as handle:
            return any(("docker" in line or "containerd" in line) for line in handle)
    except OSError:
        return False


def _browser_install_hint() -> str:
    """Point at the actual cause when the browser is missing in our own image.

    Inside a container "install a browser or set CHROME_PATH" is misleading:
    the image simply wasn't built with one, and the fix is a build argument.
    It's easy to lose, too — a plain ``docker compose build`` defaults it back
    to 0 and quietly produces an image with no browser.
    """
    if not _in_container():
        return ""
    return (
        ". This image was built without a browser — rebuild with "
        "WITH_SOLVER=1 (put it in backend/.env so it survives future builds), "
        "then `docker compose build && docker compose up -d`"
    )


def engine_env(settings: Settings | None = None) -> dict[str, str]:
    """Environment overrides for the engine subprocess.

    Always sets ``SPOTIFLAC_VERIFY_CMD`` — to the solver command when auto
    verification is on and usable, and to the empty string otherwise, which
    the engine reads as "print the challenge URL and let a human deal with
    it". Setting it either way means a stale value in the parent's environment
    can't leak into the child.
    """
    if settings is None:
        from .config import get_settings

        settings = get_settings()

    if not settings.auto_verify:
        return {"SPOTIFLAC_VERIFY_CMD": ""}

    custom = bool((settings.verify_command or "").strip())
    if not custom:
        # A custom command is the admin's business; only vet our own default.
        ready, why = solver_ready()
        if not ready:
            _warn_once(
                why or "solver",
                "Automatic community verification unavailable: %s. Downloads "
                "will fail until a session file is provided manually.",
                why,
            )
            return {"SPOTIFLAC_VERIFY_CMD": ""}

    env = {"SPOTIFLAC_VERIFY_CMD": json.dumps(solver_argv(settings))}

    existing = os.environ.get("PYTHONPATH", "")
    root = str(_PACKAGE_ROOT)
    if root not in existing.split(os.pathsep):
        env["PYTHONPATH"] = f"{root}{os.pathsep}{existing}" if existing else root
    return env


def status_report(settings: Settings) -> dict:
    """Everything the dashboard needs about verification. Never includes the
    session secret."""
    record = read_session()
    expires_at = _expiry(record) if record else None
    valid = session_is_valid(record)

    if settings.auto_verify and not (settings.verify_command or "").strip():
        ready, why = solver_ready()
    elif settings.auto_verify:
        ready, why = True, None  # custom command; we can't vet it
    else:
        ready, why = False, "auto verification is disabled (AUTO_VERIFY=false)"

    return {
        "sessionPresent": record is not None,
        "sessionValid": valid,
        "expiresAt": expires_at.isoformat() if expires_at else None,
        "expiresInSeconds": (
            round((expires_at - datetime.now(timezone.utc)).total_seconds())
            if expires_at
            else None
        ),
        "installId": (record or {}).get("install_id") or None,
        "sessionPath": str(session_path()),
        "autoVerify": settings.auto_verify,
        "solverReady": ready,
        "solverError": why,
        "solverCommand": solver_argv(settings) if settings.auto_verify else None,
    }
