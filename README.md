# InstaPlayer — Offline FLAC Player

A phone-based **offline music player** (Android-first, React Native/Expo) paired with a
**self-hosted backend**. You hand the backend a Spotify playlist/album URL; it resolves each
track's ISRC, downloads the matching lossless FLAC from hi-fi sources via
[SpotiFLAC](https://github.com/spotbye/SpotiFLAC), tags it, and fetches synced lyrics. The app
pulls those files to the phone and plays them **fully offline** — the phone owns the entire
library.

## Repository layout

```
backend/   FastAPI service that wraps SpotiFLAC (Python 3.11, Dockerized)
app/       React Native (Expo) mobile client — see app/README.md for setup
docs/      Backend technical reference
```

## ⚠️ Legal / distribution note

The backend downloads tracks from third-party hi-fi services via ISRC matching, which violates
those services' Terms of Service. **Keep the download capability strictly on your own
self-hosted backend and use it for personal use only.** The mobile client itself is a neutral
offline media player and contains no downloaders — it connects to a backend URL that *you*
supply.

## Quick start (backend)

```bash
cd backend
cp .env.example .env          # set API_KEY to a long random string
docker compose up --build
# API is now on http://localhost:8000  (docs at /docs)
```

Resolve + download a playlist:

```bash
curl -X POST http://localhost:8000/jobs \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"spotifyUrl": "https://open.spotify.com/playlist/XXXX"}'
```

## Architecture

```
Expo/RN client  ──REST + WebSocket──►  Self-hosted backend (Docker)
  • Spotify-style UI (Home/Search/Library)   • FastAPI + job queue
  • expo-audio playback (ExoPlayer/AVPlayer) • SpotiFLAC wrapper (ISRC → Tidal/Qobuz/Amazon)
  • offline FLAC store (expo-file-system)    • Go tagger + LRCLIB lyrics
  • SQLite library mirror (expo-sqlite)      • transient job files, deleted after pull
```

## Backend configuration

All settings are read from `backend/.env` (copy `backend/.env.example` and edit).
Every variable is optional except `API_KEY`.

| Variable | Default | What it does |
|---|---|---|
| `API_KEY` | `change-me-in-.env` | Bearer token the phone must send with every request — **change this** |
| `DEFAULT_SERVICES` | `deezer,amazon,qobuz,tidal` | Comma-separated source order for SpotiFLAC. Remove a name to skip it entirely (e.g. `DEFAULT_SERVICES=deezer,amazon,qobuz` to skip Tidal when its proxies are all down) |
| `QUALITY` | `LOSSLESS` | SpotiFLAC quality tier: `LOSSLESS`, `HIGH`, or `LOW` |
| `TRACK_MAX_RETRIES` | `1` | Retries per track (0 = one attempt only, 1 = one retry, …). Higher values can help with transient errors but worsen rate-limit exhaustion on shared resolvers |
| `QOBUZ_TOKEN` | *(unset)* | Qobuz account token. When set, SpotiFLAC uses authenticated Qobuz — **no proxy required, most reliable source** |
| `JOB_RETENTION_HOURS` | `6` | How long a finished job's files are kept on the server before auto-deletion |
| `DATA_DIR` | `./data` | Where job files and the SQLite DB live inside the container |
| `PROBE_SPOTIFY_URL` | *(a well-known track)* | Track downloaded by `POST /downloader/probe` to verify SpotiFLAC works end-to-end |
| `PROBE_TIMEOUT_SECONDS` | `240` | Hard cap on a probe run |
| `PROBE_INTERVAL_MINUTES` | `60` | Auto-run the probe every N minutes so `/downloader/probe` and the app's status card answer instantly from the stored result. `0` disables. Each probe downloads one track |

**Tip:** If downloads are consistently failing, the most common cause is that the third-party
proxy APIs SpotiFLAC uses are temporarily down or rate-limited. Options:
- Add a `QOBUZ_TOKEN` (Qobuz account) for a proxy-free download path
- Set `DEFAULT_SERVICES=deezer,amazon,qobuz` to skip Tidal entirely when its proxies are dead
- Try again later — the public proxy infrastructure is community-maintained and sometimes goes down

## Security

The backend must not be exposed unauthenticated. Use the bearer `API_KEY`, and expose it over
a VPN (Tailscale/WireGuard) or a TLS reverse proxy rather than a raw open port.
