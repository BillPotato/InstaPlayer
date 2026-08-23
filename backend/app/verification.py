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
import urllib.parse
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
    # The proxy is deliberately *not* passed here: argv is visible in `ps` and
    # is echoed back by status_report. It travels in the environment instead.
    return argv


def proxy_url(settings: Settings) -> str | None:
    """The solver's proxy as a URL, from either configuration form.

    ``VERIFY_PROXY`` wins if set; otherwise the four ``PROXY_*`` parts are
    assembled, quoting the credentials so a password containing ``@`` or ``:``
    survives — which is why the split form exists.
    """
    explicit = (settings.verify_proxy or "").strip()
    if explicit:
        return explicit
    host = (settings.proxy_host or "").strip()
    if not host:
        return None

    scheme = (settings.proxy_scheme or "http").strip()
    port = f":{settings.proxy_port}" if settings.proxy_port else ""
    login = (settings.proxy_login or "").strip()
    if not login:
        return f"{scheme}://{host}{port}"
    credentials = urllib.parse.quote(login, safe="")
    password = (settings.proxy_password or "").strip()
    if password:
        credentials += f":{urllib.parse.quote(password, safe='')}"
    return f"{scheme}://{credentials}@{host}{port}"


def proxy_endpoint(settings: Settings) -> str | None:
    """``host:port`` with no credentials — safe to report and to log."""
    url = proxy_url(settings)
    if not url:
        return None
    parsed = urllib.parse.urlparse(url)
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.hostname}{port}"


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
        return {"SPOTIFLAC_VERIFY_CMD": "", "TS_PROXY": "", "TS_TIMEZONE": ""}

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
            return {"SPOTIFLAC_VERIFY_CMD": "", "TS_PROXY": "", "TS_TIMEZONE": ""}

    env = {"SPOTIFLAC_VERIFY_CMD": json.dumps(solver_argv(settings))}

    # Carried in the environment rather than argv. The password still reaches
    # the engine and, through it, the solver — that is the point — but the
    # environment is only readable by this container's own processes, whereas
    # argv shows up in `ps` and is echoed back by status_report over HTTP.
    # Set both keys unconditionally, so clearing the setting clears the child's.
    proxy = proxy_url(settings)
    env["TS_PROXY"] = proxy or ""
    env["TS_TIMEZONE"] = (settings.verify_timezone or "").strip()

    # Go's default transport honours these, so the engine's community calls
    # leave from the same address that solved the captcha — which the API's
    # signature check requires. It points at the local splitter rather than
    # the paid proxy directly, so only PROXY_HOSTS pay for the exit and the
    # audio goes direct. Loopback is excluded so the engine can still reach
    # its own verification callback.
    if proxy and settings.proxy_engine:
        from . import proxy_splitter

        hosts = tuple(h.strip() for h in settings.proxy_hosts.split(",") if h.strip())
        local = proxy_splitter.ensure_running(settings.proxy_split_port, proxy, hosts)
        env["HTTP_PROXY"] = env["HTTPS_PROXY"] = local
        env["http_proxy"] = env["https_proxy"] = local
        env["NO_PROXY"] = env["no_proxy"] = "127.0.0.1,localhost,::1"
        log.info(
            "engine routed via the local splitter; %s",
            f"upstream for {', '.join(hosts)}" if hosts
            else "LOG-ONLY (nothing upstream yet — set PROXY_HOSTS)",
        )

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
        # Endpoint only. The credentials do travel — down the subprocess
        # chain in the environment — but never into this report, which is
        # returned over HTTP, nor into argv, which `ps` shows.
        "proxy": proxy_endpoint(settings),
        "timezone": (settings.verify_timezone or "").strip() or None,
        "solverReady": ready,
        "solverError": why,
        "solverCommand": solver_argv(settings) if settings.auto_verify else None,
    }
