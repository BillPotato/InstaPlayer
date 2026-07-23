# InstaPlayer — Offline FLAC Player

A phone-based **offline music player** (Android-first, React Native/Expo) paired with a
**self-hosted backend**. You hand the backend a Spotify playlist/album URL; it resolves each
track's ISRC, downloads the matching lossless FLAC from hi-fi sources via
[SpotiFLAC](https://github.com/spotbye/SpotiFLAC), tags it, and fetches synced lyrics. The app
pulls those files to the phone and plays them **fully offline** — the phone owns the entire
library.

## Repository layout

```
backend/   FastAPI service (Python 3.11) driving the vendored SpotiFLAC Go engine, Dockerized
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
# Admin dashboard at http://localhost:8000/admin — status light, force-probe
# button, live logs, active-download progress + cancel, cooldown countdown.
# It asks for your API_KEY on first load (stored in the browser).
# User status page at http://localhost:8000/ — public, no key: is the server
# working, health timeline, current-download progress, last download outcome.
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
| `DEFAULT_SERVICES` | `qobuz,tidal,amazon` | Comma-separated source order for the engine. Only `qobuz`/`tidal`/`amazon` are download providers (deezer is metadata/art only upstream — no downloader). Remove a name to skip it (e.g. `DEFAULT_SERVICES=qobuz,amazon` to skip Tidal when its proxies are down) |
| `QUALITY` | `LOSSLESS` | Quality profile: `LOSSLESS` (16-bit) or `HI_RES` (24-bit). The engine maps this onto each provider's own quality code |
| `TRACK_MAX_RETRIES` | `6` | How many times the engine retries a community-endpoint request on transient errors (429/502/504) before giving up, with backoff between tries (the `waiting Ns before retry (i/N)` lines). `0` = one attempt, no retries — lower it to fail faster when the community servers are flaky |
| `QOBUZ_TOKEN` | *(unset)* | Optional custom Qobuz API base URL (`https://…`) forwarded to the engine. Leave unset to use the built-in community endpoint |
| `JOB_RETENTION_HOURS` | `6` | How long a finished job's files are kept on the server before auto-deletion |
| `DATA_DIR` | `./data` | Where job files and the SQLite DB live inside the container |
| `SPOOTY_BASE_URL` | *(unset)* | Base URL of an optional [Spooty](#spooty-fallback) instance used as a fallback when SpotiFLAC returns zero tracks, e.g. `http://spooty:3000`. Leave unset to disable the fallback entirely |
| `SPOOTY_FORMAT` | `flac` | File extension Spooty is configured to produce (its own `FORMAT` env var). Must stay `flac` — the backend only scans for `*.flac` files |
| `PROBE_SPOTIFY_URL` | *(a well-known track)* | Track downloaded by `POST /downloader/probe` to verify SpotiFLAC works end-to-end |
| `PROBE_TIMEOUT_SECONDS` | `240` | Hard cap on a probe run |
| `PROBE_INTERVAL_MINUTES` | `60` | Auto-run the probe every N minutes so `/downloader/probe` and the app's status card answer instantly from the stored result. `0` disables. Each probe downloads one track |
| `SPOTIFLAC_DL_BIN` | *(on `PATH`)* | Path to the `spotiflac-dl` engine binary. Unset = resolve it from `PATH` (the image installs it to `/usr/local/bin`). Set only for a non-standard location |
| `LOG_RETENTION_DAYS` | `30` | How many days of per-day log files (`data/logs/YYYY-MM-DD.jsonl`, browsable in the `/admin` dashboard) to keep; older ones are pruned on startup. `0` = keep forever |

The engine is the vendored **SpotiFLAC Go binary** (`backend/spotiflac-go/`), built from
source into the image — not a pip package. To pull a newer upstream, run
`scripts/update-spotiflac.sh` and rebuild the image; `GET /downloader/status` reports the
engine's `version`.

**Tip:** If downloads are consistently failing, the most common cause is that the third-party
proxy APIs the engine uses are temporarily down or rate-limited. Options:
- Set `DEFAULT_SERVICES=qobuz,amazon` to skip Tidal entirely when its proxies are dead
- Try again later — the public proxy infrastructure is community-maintained and sometimes goes down
- Set up the [Spooty fallback](#spooty-fallback) below so jobs still complete (at lower quality)
  when SpotiFLAC can't get anything

### Spooty fallback

[Spooty](https://github.com/Raiper34/spooty) is a separate self-hosted downloader that
resolves track metadata from the Spotify API and fetches **lossy audio from YouTube**. It is
**not a replacement** for SpotiFLAC's lossless sources — it's wired in purely as a last-resort
fallback for when SpotiFLAC comes back with zero tracks (e.g. all its proxies are down). When
`SPOOTY_BASE_URL` is unset, none of this is used and behavior is unchanged.

To enable it:

1. Build a Spooty image from a working checkout (the upstream repo has been unstable —
   you may need a fork): `docker build -t spooty:local /path/to/spooty/checkout`
2. Create a [Spotify Developer App](https://developer.spotify.com/dashboard) to obtain a
   `Client ID`/`Client Secret` (Spooty needs these to read playlist metadata — same
   credentials Spooty's own README describes).
3. Add to `backend/.env`:
   ```
   SPOOTY_BASE_URL=http://spooty:3000
   SPOOTY_SPOTIFY_CLIENT_ID=your_client_id
   SPOOTY_SPOTIFY_CLIENT_SECRET=your_client_secret
   ```
4. Start everything including the Spooty container (it's behind a Compose profile so it
   doesn't run unless you ask for it):
   ```bash
   docker compose --profile spooty up --build
   ```

The backend reaches Spooty over the Compose network at `http://spooty:3000` — no port needs
publishing. Keep Spooty's `FORMAT` set to `flac` (already the default in `docker-compose.yml`)
so its output matches `SPOOTY_FORMAT` and gets picked up by the ingestion scanner.

## Public exposure (TLS proxy)

For serving beyond your LAN/VPN, a Caddy reverse proxy is included as a compose overlay. It
terminates TLS (automatic Let's Encrypt), rate-limits the unauthenticated pages (`/` and
`/public/status`: 10 req/s per IP; everything else 30 req/s), writes access logs separately
from the app's own logs (`backend/logs/caddy/access.log`), and takes uvicorn's `:8000` off
the network — only 80/443 are published (the backend stays reachable on the host at
`127.0.0.1:8000` for debugging).

```bash
cd backend
echo "DOMAIN=music.example.com" >> .env   # a hostname that resolves to this server
docker compose -f docker-compose.yml -f docker-compose.public.yml up --build -d
```

Point the phone app at `https://your-domain` (no port). Without a `DOMAIN`, Caddy serves
`localhost` with a self-signed internal-CA certificate — fine for a look around, but phones
will reject it; use a real domain (a free DuckDNS name works) for production. If you'd rather
not expose anything, skip this overlay entirely and use Tailscale/WireGuard as before.

## Backups

Everything the backend needs to survive a disk loss lives in `backend/data/`: the SQLite job
DB, per-day logs, probe cache + health history, admin state, and the engine home with the
community session file. `./scripts/backup-data.sh` tars it (minus the disposable per-job
download dirs) into `./backups/`, keeping the newest 14 (`KEEP=N` to change). Run it from
cron, e.g. daily at 04:00:

```
0 4 * * * cd /path/to/InstaPlayer && ./scripts/backup-data.sh >> backups/backup.log 2>&1
```

Copy `backups/` somewhere off-machine if the server disk is the thing you're insuring
against. Restoring = stop the stack, untar over `backend/data/`, start it again.

## Security

The backend must not be exposed unauthenticated. Use the bearer `API_KEY` (long and random —
e.g. `openssl rand -hex 32` — never the placeholder), and expose the server only through the
TLS proxy overlay above or over a VPN (Tailscale/WireGuard); never publish raw `:8000` to the
internet, since the API key would travel unencrypted.
