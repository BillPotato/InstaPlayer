"""Unit tests for ingest_track de-dupe + file placement (no real FLAC needed)."""
import os
import tempfile
from pathlib import Path

os.environ.setdefault("API_KEY", "test-key")
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="musicapp-ingest-"))

from app.config import get_settings  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.ingest import FlacMeta, ingest_track, link_to_playlist  # noqa: E402
from app.models import Playlist, Track  # noqa: E402

init_db()
settings = get_settings()


def _dummy_flac(name: str) -> Path:
    p = settings.jobs_dir / name
    p.write_bytes(b"FLAC-FAKE-AUDIO")
    return p


def test_ingest_and_dedupe_by_isrc():
    with SessionLocal() as s:
        meta1 = FlacMeta(
            src_path=_dummy_flac("a.flac"),
            title="Song",
            artist="Artist",
            album="Album",
            isrc="USABC1234567",
            art_bytes=b"\x89PNG-fake",
            art_mime="image/png",
        )
        t1 = ingest_track(s, meta1, settings)
        s.commit()

        # File was moved into the music library and art written alongside.
        assert Path(t1.file_path).exists()
        assert t1.file_path.endswith(".flac")
        assert t1.file_size > 0
        assert t1.art_path and Path(t1.art_path).exists()
        assert not meta1.src_path.exists()  # moved, not copied

        # Same ISRC again → returns existing row, discards the duplicate file.
        meta2 = FlacMeta(src_path=_dummy_flac("b.flac"), title="Song", isrc="USABC1234567")
        t2 = ingest_track(s, meta2, settings)
        s.commit()
        assert t2.id == t1.id
        assert not meta2.src_path.exists()
        assert s.query(Track).count() == 1


def test_playlist_linking_is_idempotent():
    with SessionLocal() as s:
        pl = Playlist(name="P")
        s.add(pl)
        s.flush()
        meta = FlacMeta(src_path=_dummy_flac("c.flac"), title="X", isrc="USXYZ7654321")
        t = ingest_track(s, meta, settings)
        link_to_playlist(s, pl, t, 0)
        link_to_playlist(s, pl, t, 0)  # second call must not duplicate
        s.commit()
        assert len(pl.track_links) == 1


if __name__ == "__main__":
    test_ingest_and_dedupe_by_isrc()
    test_playlist_linking_is_idempotent()
    print("ingest tests passed")
