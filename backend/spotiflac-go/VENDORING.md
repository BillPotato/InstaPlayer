# Vendored SpotiFLAC Go engine

`backend/` here is copied verbatim from the upstream desktop app
[spotbye/SpotiFLAC](https://github.com/spotbye/SpotiFLAC) (MIT, see `LICENSE`) — the
Wails-free `backend/` Go package only. We build a small headless CLI
(`cmd/spotiflac-dl`) against it and the FastAPI backend runs that binary as a
subprocess (replacing the lagging `SpotiFLAC` pip package).

- **Vendored from upstream commit:** `02cfd11` (v7.2.0).
- **Removed from the copy** (GUI-only, pulled in Wails): `file_dialog.go`,
  `folder.go`, `lyrics_reader.go`. The download path doesn't use them, and
  dropping them lets the module build with `CGO_ENABLED=0` and no Wails.
- **Build:** pure Go, `CGO_ENABLED=0` → static binary. taglib runs via wazero
  (WASM), so no C toolchain / libtag is needed. ffmpeg is invoked at runtime.

## Local patches (re-applied automatically by the update script)

- **Configurable retry budget.** Upstream declares `communityRateLimitMaxRetries`
  as a `const`; the update script rewrites it to a `var` in
  `community_endpoints.go` and adds `community_retries_patch.go` with a setter, so
  `spotiflac-dl --max-retries` (→ `TRACK_MAX_RETRIES`) works. `go build` will fail
  with "undefined: SetCommunityRateLimitMaxRetries" if this wasn't applied.

## Community verification (v7.2.0+)

The community download endpoints now require a one-time human check (Cloudflare)
that issues an HMAC-signing **session** stored at `$HOME/.spotiflac/community_session.json`.
The headless CLI **cannot** perform that verification (it has no browser), so it
relies on a session file created by the official desktop app and copied onto the
server. The request signature includes the app version — kept in sync via
`upstreamAppVersion` in `cmd/spotiflac-dl/main.go` (currently `7.2.0`).

To update to a newer upstream, run `scripts/update-spotiflac.sh` from the repo
root: it re-copies `backend/` (minus the three GUI files), re-applies the local
patches, runs `go mod tidy`, and verifies the `CGO_ENABLED=0` build. Then bump
the commit hash above (and `upstreamAppVersion` in `main.go`) and rebuild the
backend image.
