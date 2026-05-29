"""Smoke tests that exercise the app without the heavy SpotiFLAC dependency.

Run from backend/:  .venv\\Scripts\\python.exe tests\\test_smoke.py
"""
import os
import tempfile

os.environ.setdefault("API_KEY", "test-key")
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="musicapp-test-"))

from fastapi.testclient import TestClient  # noqa: E402

from app.db import init_db  # noqa: E402
from app.main import app  # noqa: E402

init_db()
client = TestClient(app)
AUTH = {"Authorization": "Bearer test-key"}


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_auth_required():
    # A protected endpoint with no bearer → rejected.
    assert client.get("/jobs/whatever").status_code in (401, 403)
    # Wrong key → explicit 401 from our comparison.
    assert client.get("/jobs/whatever", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_unknown_job_404():
    assert client.get("/jobs/deadbeef", headers=AUTH).status_code == 404
    assert client.get("/jobs/deadbeef/manifest", headers=AUTH).status_code == 404


def test_invalid_job_id_rejected():
    # Non-alphanumeric ids are rejected before any filesystem access.
    assert client.get("/jobs/..%2f..%2fetc/manifest", headers=AUTH).status_code in (400, 404)


def test_job_create_validates_url():
    for bad in ["", "https://example.com/not-spotify", "   "]:
        r = client.post("/jobs", headers=AUTH, json={"spotifyUrl": bad})
        assert r.status_code == 422, f"Expected 422 for {bad!r}, got {r.status_code}"
    # A valid Spotify URL is accepted (download runs in the background).
    r = client.post("/jobs", headers=AUTH,
                    json={"spotifyUrl": "https://open.spotify.com/playlist/abc"})
    assert r.status_code != 422


def test_schema_migration_idempotent():
    from app.db import init_db as _init
    _init()  # second call must be a no-op


if __name__ == "__main__":
    test_health()
    test_auth_required()
    test_unknown_job_404()
    test_invalid_job_id_rejected()
    test_job_create_validates_url()
    test_schema_migration_idempotent()
    print("all smoke tests passed")
