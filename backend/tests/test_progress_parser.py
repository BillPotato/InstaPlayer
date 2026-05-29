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


def test_no_false_positives():
    assert _collect(["nothing interesting here", "downloading chunk 12"]) == []


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
    test_no_false_positives()
    test_tee_forwards_and_parses()
    print("progress parser tests passed")
