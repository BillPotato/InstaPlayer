"""Smoke tests that exercise the app without the heavy SpotiFLAC dependency.

Run from backend/:  .venv\\Scripts\\python.exe -m pytest -q   (or run directly)
"""
import os
import tempfile

os.environ.setdefault("API_KEY", "test-key")
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="musicapp-test-"))

from fastapi.testclient import TestClient  # noqa: E402

from app.db import init_db  # noqa: E402
from app.main import app  # noqa: E402

init_db()  # startup event only fires under the TestClient context manager
client = TestClient(app)
AUTH = {"Authorization": "Bearer test-key"}


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_auth_required():
    # No bearer at all → rejected (FastAPI HTTPBearer returns 401/403 by version).
    assert client.get("/playlists").status_code in (401, 403)
    # Wrong key → explicit 401 from our comparison.
    assert client.get("/playlists", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_empty_library():
    r = client.get("/playlists", headers=AUTH)
    assert r.status_code == 200
    assert r.json() == []
    assert client.get("/tracks", headers=AUTH).json() == []


def test_unknown_track_404():
    assert client.get("/tracks/nope", headers=AUTH).status_code == 404


if __name__ == "__main__":
    test_health()
    test_auth_required()
    test_empty_library()
    test_unknown_track_404()
    print("all smoke tests passed")
