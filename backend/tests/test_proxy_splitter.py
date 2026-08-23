"""Tests for the split proxy.

The routing decision is the part worth pinning down: getting it wrong either
sends FLACs through a per-gigabyte proxy or sends signed API calls direct,
and the second failure looks like a broken session rather than a routing bug.
An end-to-end tunnel is exercised too, against a local server.
"""
import http.server
import os
import socket
import tempfile
import threading
import urllib.request

import pytest

os.environ.setdefault("API_KEY", "test-key")
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="musicapp-split-"))

from app.proxy_splitter import SplittingProxy, host_matches  # noqa: E402


# --- which host goes where -------------------------------------------------


def test_exact_and_subdomain_match():
    rules = ("example.com",)
    assert host_matches("example.com", rules)
    assert host_matches("api.example.com", rules)
    assert host_matches("a.b.example.com", rules)


def test_matching_stops_at_a_dot():
    # The expensive mistake: a substring match would route unrelated hosts.
    assert not host_matches("notexample.com", ("example.com",))
    assert not host_matches("example.com.evil.net", ("example.com",))


def test_port_is_ignored():
    assert host_matches("example.com:443", ("example.com",))


def test_case_and_stray_dots():
    assert host_matches("API.Example.COM.", (" example.com ",))


def test_no_rules_matches_nothing():
    # Log-only mode: everything goes direct.
    assert not host_matches("example.com", ())
    assert not host_matches("example.com", ("",))


# --- upstream parsing ------------------------------------------------------


def test_upstream_credentials_become_basic_auth():
    proxy = SplittingProxy(1, "http://bob:s3cr3t@gate:8080", ())
    host, port, auth = proxy._upstream
    assert (host, port) == ("gate", 8080)
    # base64("bob:s3cr3t")
    assert auth == "Ym9iOnMzY3IzdA=="


def test_upstream_without_credentials():
    assert SplittingProxy(1, "http://gate:8080", ())._upstream == ("gate", 8080, None)


def test_no_upstream_configured():
    assert SplittingProxy(1, None, ())._upstream is None


# --- an actual connection through it ---------------------------------------


@pytest.fixture
def origin_server():
    """A plain HTTP server standing in for whatever the engine would call."""
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = b"payload"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_address[1]
    server.shutdown()


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_direct_route_forwards_the_request(origin_server):
    """With no rules the splitter is a transparent pass-through."""
    port = _free_port()
    proxy = SplittingProxy(port, None, ())
    assert proxy.start()

    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": f"http://127.0.0.1:{port}"})
    )
    with opener.open(f"http://127.0.0.1:{origin_server}/thing", timeout=10) as response:
        assert response.read() == b"payload"


def test_start_reports_a_taken_port():
    """A second process should reuse the running instance, not crash."""
    port = _free_port()
    first = SplittingProxy(port, None, ())
    assert first.start() is True
    assert SplittingProxy(port, None, ()).start() is False


if __name__ == "__main__":
    raise SystemExit(pytest.main([os.path.abspath(__file__), "-q"]))
