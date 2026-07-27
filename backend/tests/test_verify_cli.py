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


if __name__ == "__main__":
    raise SystemExit(pytest.main([os.path.abspath(__file__), "-q"]))
