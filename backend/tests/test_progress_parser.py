"""Unit tests for the SpotiFLAC stdout/stderr progress parsing."""
import os
import tempfile

os.environ.setdefault("API_KEY", "test-key")
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="musicapp-parser-"))

from app.spotiflac_adapter import _ProgressTee, _parse_line  # noqa: E402


def _collect(lines):
    updates = []
    for line in lines:
        _parse_line(line, updates.append)
    return updates


def test_parses_total_and_current():
    updates = _collect([
        "Fetching metadata…",
        "Found 57 track(s) in: Liked clone",
        "[INFO] SpotiFLAC.downloader: [base] Trying: The Cassette — Nắng",
        "  x  tidal  ·  some.host  ·  HTTP 503",
    ])
    assert {"total": 57} in updates
    assert {"current": "The Cassette — Nắng"} in updates


def test_parses_track_header():
    # New SpotiFLAC emits an authoritative per-track header carrying both the
    # total ([N/M]) and the current track.
    updates = _collect([
        "Track [1/2] Bohemian Rhapsody — Queen (A Night at the Opera)",
        "Track [2/2] Billie Jean — Michael Jackson (Thriller)",
    ])
    assert {"total": 2, "current": "Bohemian Rhapsody — Queen"} in updates
    assert {"total": 2, "current": "Billie Jean — Michael Jackson"} in updates


def test_track_header_survives_truncated_album():
    # album[:32] can cut mid-text, leaving an unbalanced "(" in the line; the
    # title and artist must still come through cleanly.
    updates = _collect([
        "Track [1/2] Bohemian Rhapsody — Queen (Bohemian Rhapsody (The Original ",
    ])
    assert {"total": 2, "current": "Bohemian Rhapsody — Queen"} in updates


def test_track_header_keeps_parenthetical_title():
    updates = _collect([
        "Track [3/5] Song Title (Remastered) — The Artist (Some Album)",
    ])
    assert {"total": 5, "current": "Song Title (Remastered) — The Artist"} in updates


def test_no_false_positives():
    assert _collect(["nothing interesting here", "downloading chunk 12"]) == []


def test_tqdm_bar_is_not_a_header():
    # The per-track tqdm bar ("Track: <name>  : 12%|…") must NOT be parsed as a
    # header — only "Track [N/M]" is.
    assert _collect([
        "Track: Billie Jean       :   0%|          | 0.00/109M [00:",
        "Progress:   0%|          | 0/2 [00:07<?, ?it/s]",
    ]) == []


def test_tee_forwards_and_parses():
    import io

    sink = io.StringIO()
    seen = []
    tee = _ProgressTee(sink, lambda line: _parse_line(line, seen.append))
    tee.write("Found 3 track(s)\n")
    tee.write("partial line without newline")
    # Forwarded verbatim to the underlying stream.
    assert sink.getvalue().startswith("Found 3 track(s)\n")
    # Parsed the completed line; the partial line is buffered, not yet parsed.
    assert {"total": 3} in seen


if __name__ == "__main__":
    test_parses_total_and_current()
    test_parses_track_header()
    test_track_header_survives_truncated_album()
    test_track_header_keeps_parenthetical_title()
    test_no_false_positives()
    test_tqdm_bar_is_not_a_header()
    test_tee_forwards_and_parses()
    print("progress parser tests passed")
