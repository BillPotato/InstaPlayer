# Vendored SpotiFLAC Go engine

`backend/` here is copied verbatim from the upstream desktop app
[spotbye/SpotiFLAC](https://github.com/spotbye/SpotiFLAC) (MIT, see `LICENSE`) — the
Wails-free `backend/` Go package only. We build a small headless CLI
(`cmd/spotiflac-dl`) against it and the FastAPI backend runs that binary as a
subprocess (replacing the lagging `SpotiFLAC` pip package).

- **Vendored from upstream commit:** `3f755f5` (2026-07-12).
- **Removed from the copy** (GUI-only, pulled in Wails): `file_dialog.go`,
  `folder.go`, `lyrics_reader.go`. The download path doesn't use them, and
  dropping them lets the module build with `CGO_ENABLED=0` and no Wails.
- **Build:** pure Go, `CGO_ENABLED=0` → static binary. taglib runs via wazero
  (WASM), so no C toolchain / libtag is needed. ffmpeg is invoked at runtime.

To update to a newer upstream: re-copy `backend/` (minus the three GUI files),
`go mod tidy`, rebuild, and bump the commit hash above. (A helper script lands
in a later step.)
