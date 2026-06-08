"""Unit tests for the Spooty fallback adapter (no real Spooty instance needed —
HTTP is mocked via httpx.MockTransport)."""
import contextlib
import os
import tempfile
from pathlib import Path

os.environ.setdefault("API_KEY", "test-key")
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="musicapp-spooty-"))

import httpx  # noqa: E402

from app.spooty_adapter import SpootyError, run_spooty  # noqa: E402

BASE_URL = "http://spooty.local:3000"


@contextlib.contextmanager
def _patched_client(handler):
    """Make run_spooty's internal httpx.Client use a mocked transport."""
    import app.spooty_adapter as mod

    real_client = httpx.Client

    def fake_client(*, base_url, timeout):
        return real_client(base_url=base_url, timeout=timeout,
                           transport=httpx.MockTransport(handler))

    mod.httpx.Client = fake_client
    try:
        yield
    finally:
        mod.httpx.Client = real_client


def _job_dir(name: str) -> Path:
    return Path(tempfile.mkdtemp(prefix=f"spooty-job-{name}-"))


# ---- success path --------------------------------------------------------

def test_full_success_flow_downloads_completed_tracks():
    calls = {"track_polls": 0, "deleted": False}
    track_batches = [
        # First poll: still in progress.
        [
            {"id": 1, "index": 1, "artist": "Artist A", "name": "Song A", "status": 3},
            {"id": 2, "index": 2, "artist": "Artist B", "name": "Song B", "status": 1},
        ],
        # Second poll: all done — one completed, one errored.
        [
            {"id": 1, "index": 1, "artist": "Artist A", "name": "Song A", "status": 4},
            {"id": 2, "index": 2, "artist": "Artist B", "name": "Song B", "status": 5},
        ],
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        if method == "POST" and path == "/api/playlist":
            return httpx.Response(201)
        if method == "GET" and path == "/api/playlist":
            return httpx.Response(200, json=[
                {"id": 9, "name": "My Cool Playlist", "spotifyUrl": "spotify:playlist:x",
                 "error": None, "createdAt": 1},
            ])
        if method == "GET" and path == "/api/track/playlist/9":
            idx = min(calls["track_polls"], len(track_batches) - 1)
            calls["track_polls"] += 1
            return httpx.Response(200, json=track_batches[idx])
        if method == "GET" and path == "/api/track/download/1":
            return httpx.Response(200, content=b"fake-flac-bytes")
        if method == "DELETE" and path == "/api/playlist/9":
            calls["deleted"] = True
            return httpx.Response(200)
        raise AssertionError(f"unexpected request: {method} {path}")

    out_dir = _job_dir("ok")
    progress_updates = []
    with _patched_client(handler):
        run_spooty("spotify:playlist:x", out_dir, BASE_URL, "flac", progress_updates.append)

    written = list((out_dir / "My Cool Playlist").glob("*.flac"))
    assert len(written) == 1
    assert written[0].name == "01 - Artist A - Song A.flac"
    assert written[0].read_bytes() == b"fake-flac-bytes"
    assert calls["deleted"] is True
    assert any("total" in u for u in progress_updates)


# ---- failure paths --------------------------------------------------------

def test_zero_completed_raises_and_still_cleans_up():
    calls = {"deleted": False}

    def handler(request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        if method == "POST" and path == "/api/playlist":
            return httpx.Response(201)
        if method == "GET" and path == "/api/playlist":
            return httpx.Response(200, json=[
                {"id": 5, "name": "Empty", "spotifyUrl": "spotify:playlist:y",
                 "error": None, "createdAt": 1},
            ])
        if method == "GET" and path == "/api/track/playlist/5":
            return httpx.Response(200, json=[
                {"id": 1, "index": 1, "artist": "A", "name": "B", "status": 5},
            ])
        if method == "DELETE" and path == "/api/playlist/5":
            calls["deleted"] = True
            return httpx.Response(200)
        raise AssertionError(f"unexpected request: {method} {path}")

    out_dir = _job_dir("zero")
    with _patched_client(handler):
        try:
            run_spooty("spotify:playlist:y", out_dir, BASE_URL)
            assert False, "expected SpootyError"
        except SpootyError:
            pass
    assert calls["deleted"] is True


def test_playlist_resolution_error_raises_immediately():
    def handler(request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        if method == "POST" and path == "/api/playlist":
            return httpx.Response(201)
        if method == "GET" and path == "/api/playlist":
            return httpx.Response(200, json=[
                {"id": 7, "name": None, "spotifyUrl": "spotify:playlist:z",
                 "error": "Invalid Spotify URL", "createdAt": 1},
            ])
        if method == "DELETE" and path == "/api/playlist/7":
            return httpx.Response(200)
        raise AssertionError(f"unexpected request: {method} {path}")

    out_dir = _job_dir("err")
    with _patched_client(handler):
        try:
            run_spooty("spotify:playlist:z", out_dir, BASE_URL)
            assert False, "expected SpootyError"
        except SpootyError as exc:
            assert "Invalid Spotify URL" in str(exc)


def test_transport_error_is_wrapped():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    out_dir = _job_dir("transport")
    with _patched_client(handler):
        try:
            run_spooty("spotify:playlist:w", out_dir, BASE_URL)
            assert False, "expected SpootyError"
        except SpootyError:
            pass


if __name__ == "__main__":
    test_full_success_flow_downloads_completed_tracks()
    test_zero_completed_raises_and_still_cleans_up()
    test_playlist_resolution_error_raises_immediately()
    test_transport_error_is_wrapped()
    print("spooty adapter tests passed")
