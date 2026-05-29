"""Unit tests for the manifest builder (no real FLAC / no SpotiFLAC needed)."""
import os
import tempfile
from pathlib import Path

os.environ.setdefault("API_KEY", "test-key")
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="musicapp-ingest-"))

from app.ingest import (  # noqa: E402
    MANIFEST_NAME,
    _playlist_name,
    build_manifest,
    load_manifest,
)


def _job_dir(name: str) -> Path:
    d = Path(tempfile.mkdtemp(prefix=f"job-{name}-"))
    return d


def test_empty_dir_yields_empty_manifest():
    d = _job_dir("empty")
    manifest = build_manifest(d, "https://open.spotify.com/playlist/x")
    assert manifest["trackCount"] == 0
    assert manifest["tracks"] == []
    assert (d / MANIFEST_NAME).exists()
    # Round-trips through load_manifest.
    assert load_manifest(d) == manifest


def test_unparseable_flac_is_skipped_not_fatal():
    d = _job_dir("bad")
    (d / "broken.flac").write_bytes(b"not really a flac")
    manifest = build_manifest(d)  # must not raise
    assert manifest["trackCount"] == 0


def test_load_manifest_missing_returns_none():
    d = _job_dir("none")
    assert load_manifest(d) is None


def test_playlist_name_uses_top_subfolder():
    d = _job_dir("named")
    sub = d / "Cool Album"
    sub.mkdir()
    f = sub / "1.flac"
    f.write_bytes(b"x")
    assert _playlist_name(d, [f]) == "Cool Album"
    assert _playlist_name(d, []) == "Imported playlist"


if __name__ == "__main__":
    test_empty_dir_yields_empty_manifest()
    test_unparseable_flac_is_skipped_not_fatal()
    test_load_manifest_missing_returns_none()
    test_playlist_name_uses_top_subfolder()
    print("ingest tests passed")
