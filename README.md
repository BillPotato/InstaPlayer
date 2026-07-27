# InstaPlayer

A phone-based **offline music player** (Android-first, React Native/Expo) paired with a
**self-hosted backend** FLAC downloader. You hand the backend a Spotify playlist/album URL; it resolves each
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
| `PROBE_SPOTIFY_URL` | *(a well-known track)* | Track downloaded by `POST /downloader/probe` to verify SpotiFLAC works end-to-end |
| `PROBE_TIMEOUT_SECONDS` | `240` | Hard cap on a probe run |
| `PROBE_INTERVAL_MINUTES` | `60` | Auto-run the probe every N minutes so `/downloader/probe` and the app's status card answer instantly from the stored result. `0` disables. Each probe downloads one track |
| `SPOTIFLAC_DL_BIN` | *(on `PATH`)* | Path to the `spotiflac-dl` engine binary. Unset = resolve it from `PATH` (the image installs it to `/usr/local/bin`). Set only for a non-standard location |
| `LOG_RETENTION_DAYS` | `30` | How many days of per-day log files (`data/logs/YYYY-MM-DD.jsonl`, browsable in the `/admin` dashboard) to keep; older ones are pruned on startup. `0` = keep forever |
| `SPOTIFLAC_ENGINE_HOME` | `/data/engine-home` (Docker) | Directory the engine uses as its `$HOME`. Its community-endpoint session lives at `<here>/.spotiflac/community_session.json` — see [Community verification](#community-verification-captcha). Unset = engine inherits the server process's HOME |
| `WITH_SOLVER` | `0` | **Build-time.** `1` puts Google Chrome + Xvfb in the image so the container can pass the verification captcha itself. Set it in `.env` so it survives rebuilds — see [Community verification](#community-verification-captcha) |
| `TZ` | *(UTC)* | Container timezone, and so the solver's browser clock. Anti-bot scoring compares it against the address the request came from, so set it to the host's zone (only the offset matters) |
| `AUTO_VERIFY` | `true` | Let the engine pass the community captcha itself via the bundled solver. Needs a browser in the image (`WITH_SOLVER=1`); with none available it logs why and falls back to the manual route |
| `VERIFY_COMMAND` | *(unset)* | Override the solver invocation — a JSON array or a command line. The challenge URL is appended as the final argument |
| `VERIFY_HOLD_OPEN` | `5` | Seconds the solver keeps the browser open after passing the challenge, so the page can hand the grant back to the engine |

The engine is the vendored **SpotiFLAC Go binary** (`backend/spotiflac-go/`), built from
source into the image — not a pip package. To pull a newer upstream, run
`scripts/update-spotiflac.sh` and rebuild the image; `GET /downloader/status` reports the
engine's `version`.

### Community verification (captcha)

Since SpotiFLAC v7.2.0 the community download endpoints require human verification (a
Cloudflare Turnstile check) that issues a signing **session**, stored at
`<SPOTIFLAC_ENGINE_HOME>/.spotiflac/community_session.json`. Sessions expire, and without a
valid one every download fails — usually as `browser integration is not ready` or a bare
"all sources failed".

**Automatic (recommended).** The server can pass the challenge itself, using the bundled
[`turnstile_solver`](backend/turnstile_solver/README.md) to drive a real browser. It needs
a browser in the image, so build with the solver included:

```bash
cd backend
echo "WITH_SOLVER=1" >> .env        # adds Google Chrome + xvfb to the image
docker compose build && docker compose up -d
```

Put it in `.env` rather than passing `--build-arg WITH_SOLVER=1` on the command
line: compose reads `.env` when interpolating build args, so it survives every
later rebuild. A `--build-arg` applies to that one build only, and the next
plain `docker compose build` silently produces an image with no browser — the
symptom is `GET /downloader/verification` reporting `no Chromium-based browser
found`.

That's the whole setup. The engine verifies lazily — the first download that needs a
session solves the captcha and writes the file, taking an extra minute or so. To do it
ahead of time, or to check where things stand:

```bash
curl -H "Authorization: Bearer $API_KEY" https://host/downloader/verification
curl -X POST -H "Authorization: Bearer $API_KEY" https://host/downloader/verification
```

`POST` mints a session now (by running a one-track probe, which is what triggers
verification); add `?force=true` to discard the current one and start fresh. The same
report rides along on `GET /downloader/status` as `verification`.

Relevant settings: `AUTO_VERIFY=false` turns it off, `VERIFY_COMMAND` replaces the solver
invocation, `VERIFY_HOLD_OPEN` tunes how long the browser lingers after solving.

**Manual (fallback).** Without a browser — no `WITH_SOLVER`, `AUTO_VERIFY=false`, or a
solver that can't run — the engine logs the challenge URL and waits. Either solve that URL
in any browser on any machine within five minutes, or create the session elsewhere and copy
it in:

1. Run the **official SpotiFLAC desktop app** on your PC and start any download — it opens
   the verification page; solve it once. That writes
   `%USERPROFILE%\.spotiflac\community_session.json` (Linux/macOS: `~/.spotiflac/`).
2. Copy that file to the server at
   `data/engine-home/.spotiflac/community_session.json` (inside the mounted data volume;
   create the folders if needed), then it's picked up on the next download — no restart.
3. Repeat when it expires. `GET /downloader/verification` shows `expiresAt`.

**Tip:** If downloads are consistently failing, the most common cause is that the third-party
proxy APIs the engine uses are temporarily down or rate-limited. Options:
- Set `DEFAULT_SERVICES=qobuz,amazon` to skip Tidal entirely when its proxies are dead
- Try again later — the public proxy infrastructure is community-maintained and sometimes goes down

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
