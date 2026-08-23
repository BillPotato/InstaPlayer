"""Unit tests for the engine <-> solver bridge (app/verify_cli.py).

The interesting behaviour is the grant relay: the challenge page can't be
trusted to redirect to the engine's callback, so we deliver the captured grant
ourselves. No browser is driven here.
"""
import os
import tempfile
import urllib.parse

import pytest

os.environ.setdefault("API_KEY", "test-key")
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="musicapp-verifycli-"))

from app import verify_cli  # noqa: E402

CALLBACK = "http://127.0.0.1:42699/session-grant?state=fe4b8c39"
CHALLENGE = (
    "https://verify.example.io/challenge"
    f"?cb={urllib.parse.quote(CALLBACK, safe='')}&id=eyJraW5k"
)


# --- finding the callback -------------------------------------------------


def test_extracts_the_engine_callback():
    assert verify_cli.callback_url(CHALLENGE) == CALLBACK


def test_no_callback_on_the_url():
    assert verify_cli.callback_url("https://verify.example.io/challenge?id=x") is None
    assert verify_cli.callback_url("https://verify.example.io/challenge?cb=") is None


def test_non_loopback_callbacks_are_refused():
    # The grant is a credential; it goes to the local engine or nowhere.
    hostile = "https://evil.example.com/collect"
    url = f"https://verify.example.io/challenge?cb={urllib.parse.quote(hostile, safe='')}"
    assert verify_cli.callback_url(url) is None


def test_non_http_callbacks_are_refused():
    # The grant is a credential; only plain http to the engine's own loopback
    # server is a legitimate destination for it.
    for hostile in ("file://127.0.0.1/etc/passwd", "https://127.0.0.1:9/x"):
        url = f"https://v.io/challenge?cb={urllib.parse.quote(hostile, safe='')}"
        assert verify_cli.callback_url(url) is None


def test_localhost_callback_is_accepted():
    local = "http://localhost:8080/session-grant?state=a"
    url = f"https://v.io/challenge?cb={urllib.parse.quote(local, safe='')}"
    assert verify_cli.callback_url(url) == local


# --- delivering the grant -------------------------------------------------


class _FakeResponse:
    def __init__(self, status=200):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def test_grant_is_appended_to_an_existing_query(monkeypatch):
    seen = {}

    def fake_urlopen(url, timeout=None):
        seen["url"] = url
        return _FakeResponse()

    monkeypatch.setattr(verify_cli.urllib.request, "urlopen", fake_urlopen)
    assert verify_cli.deliver_grant(CALLBACK, "gr_abc123") is True

    query = urllib.parse.parse_qs(urllib.parse.urlparse(seen["url"]).query)
    assert query["grant"] == ["gr_abc123"]
    assert query["state"] == ["fe4b8c39"]  # the engine checks this


def test_grant_is_url_encoded(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        verify_cli.urllib.request,
        "urlopen",
        lambda url, timeout=None: (seen.__setitem__("url", url), _FakeResponse())[1],
    )
    verify_cli.deliver_grant(CALLBACK, "gr_a+b/c=d&e")

    query = urllib.parse.parse_qs(urllib.parse.urlparse(seen["url"]).query)
    assert query["grant"] == ["gr_a+b/c=d&e"]


def test_callback_without_a_query_gets_a_question_mark(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        verify_cli.urllib.request,
        "urlopen",
        lambda url, timeout=None: (seen.__setitem__("url", url), _FakeResponse())[1],
    )
    verify_cli.deliver_grant("http://127.0.0.1:9/cb", "g")
    assert seen["url"] == "http://127.0.0.1:9/cb?grant=g"


def test_a_dead_callback_is_not_fatal(monkeypatch):
    # Connection refused usually means the page's own redirect beat us to it
    # and the engine already shut its server down.
    def refuse(url, timeout=None):
        raise OSError("connection refused")

    monkeypatch.setattr(verify_cli.urllib.request, "urlopen", refuse)
    assert verify_cli.deliver_grant(CALLBACK, "gr_abc") is False


# --- serialising solvers --------------------------------------------------


def test_single_solver_serialises(tmp_path, monkeypatch):
    """Two solvers at once collide over the Xvfb display and the Chrome
    profile, and the loser silently drops to headless — which fails."""
    fcntl = pytest.importorskip("fcntl")  # Linux only
    lock = tmp_path / "solver.lock"
    monkeypatch.setenv("TS_LOCK_FILE", str(lock))

    holder = open(lock, "w")
    fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        waited = []
        monkeypatch.setattr(verify_cli.time, "sleep", lambda s: waited.append(s))
        with verify_cli.single_solver(timeout=0.0):
            pass
        # It gave up waiting rather than hanging, and said so.
        assert verify_cli.time is not None
    finally:
        fcntl.flock(holder, fcntl.LOCK_UN)
        holder.close()


def test_single_solver_runs_when_free(tmp_path, monkeypatch):
    pytest.importorskip("fcntl")
    monkeypatch.setenv("TS_LOCK_FILE", str(tmp_path / "solver.lock"))
    ran = []
    with verify_cli.single_solver():
        ran.append(True)
    assert ran == [True]
    # And the lock is released for the next run.
    with verify_cli.single_solver():
        ran.append(True)
    assert ran == [True, True]


# --- the fingerprint shortcut --------------------------------------------


def test_fingerprint_delegates_with_the_configured_proxy(monkeypatch):
    """The whole point of this flag: the solver's self-test knows nothing
    about the app's settings, so run from a shell it would measure the
    unproxied address and look like a broken proxy."""
    from turnstile_solver import selftest

    from app import verification

    seen = {}

    def fake_main(argv):
        seen["argv"] = argv
        return 0

    monkeypatch.setattr(verification, "proxy_url", lambda _s: "http://u:p@gate:1")
    monkeypatch.setattr(verify_cli, "apply_timezone", lambda *a, **k: None)
    monkeypatch.setattr(selftest, "main", fake_main)

    assert verify_cli.run_fingerprint() == 0
    assert seen["argv"] == ["--fingerprint", "--proxy", "http://u:p@gate:1"]


def test_fingerprint_without_a_proxy_still_runs(monkeypatch):
    from turnstile_solver import selftest

    from app import verification

    seen = {}

    def fake_main(argv):
        seen["argv"] = argv
        return 0

    monkeypatch.setattr(verification, "proxy_url", lambda _s: None)
    monkeypatch.setattr(verify_cli, "apply_timezone", lambda *a, **k: None)
    monkeypatch.setattr(selftest, "main", fake_main)

    assert verify_cli.run_fingerprint() == 0
    assert seen["argv"] == ["--fingerprint"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([os.path.abspath(__file__), "-q"]))
