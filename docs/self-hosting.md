# Self-hosting guide

Everything you need to run the InstaPlayer backend yourself: configuring it, exposing it
safely, backing it up, and diagnosing the usual failures. For a tour of how the code works,
see [backend.md](backend.md).

---

## Running it

```bash
cd backend
cp .env.example .env          # set API_KEY to a long random string
docker compose up --build
```

The API is then on `http://localhost:8000`, with interactive docs at `/docs`, the public
status page at `/`, and the admin dashboard at `/admin`.

Start a download from the command line if you want to test without the app:

```bash
curl -X POST http://localhost:8000/jobs \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"spotifyUrl": "https://open.spotify.com/playlist/XXXX"}'
```

### Architecture

```
Expo/RN client  ──REST + WebSocket──►  Self-hosted backend (Docker)
  • Spotify-style UI (Home/Search/Library)   • FastAPI + job queue
  • expo-audio playback (ExoPlayer/AVPlayer) • SpotiFLAC wrapper (ISRC → Tidal/Qobuz/Amazon)
  • offline FLAC store (expo-file-system)    • Go tagger + LRCLIB lyrics
  • SQLite library mirror (expo-sqlite)      • transient job files, deleted after pull
```

The download engine is the vendored **SpotiFLAC Go binary** (`backend/spotiflac-go/`),
compiled into the image rather than installed from pip. To pull a newer upstream, run
`scripts/update-spotiflac.sh` and rebuild; `GET /downloader/status` reports the version
currently in use.

---

## Configuration

Settings come from `backend/.env` (copy `backend/.env.example`). Everything is optional
except `API_KEY`.

| Variable | Default | What it does |
|---|---|---|
| `API_KEY` | `change-me-in-.env` | Bearer token the phone must send with every request — **change this** |
| `DEFAULT_SERVICES` | `qobuz,tidal,amazon` | Source order for the engine. Only `qobuz`/`tidal`/`amazon` download (deezer is metadata/art only upstream). Remove a name to skip it — e.g. `DEFAULT_SERVICES=qobuz,amazon` when Tidal's proxies are down |
| `QUALITY` | `LOSSLESS` | `LOSSLESS` (16-bit) or `HI_RES` (24-bit). The engine maps this onto each provider's own quality code |
| `TRACK_MAX_RETRIES` | `6` | Retries per community-endpoint request on transient errors (429/502/504), with backoff — the `waiting Ns before retry (i/N)` lines. `0` = one attempt; lower it to fail faster when the community servers are flaky |
| `QOBUZ_TOKEN` | *(unset)* | Custom Qobuz API base URL (`https://…`) forwarded to the engine. Unset = use the built-in community endpoint |
| `JOB_RETENTION_HOURS` | `6` | How long a finished job's files survive before auto-deletion |
| `DATA_DIR` | `./data` | Where job files, the SQLite DB and logs live inside the container |
| `PROBE_SPOTIFY_URL` | *(a well-known track)* | Track that `POST /downloader/probe` downloads to verify the engine end-to-end |
| `PROBE_TIMEOUT_SECONDS` | `240` | Hard cap on a probe run |
| `PROBE_INTERVAL_MINUTES` | `60` | Auto-probe every N minutes so status answers instantly from the stored result. `0` disables. Each probe downloads one real track |
| `SPOTIFLAC_DL_BIN` | *(on `PATH`)* | Path to the `spotiflac-dl` binary. Unset = resolve from `PATH` (the image installs it to `/usr/local/bin`). Set only for a non-standard location |
| `LOG_RETENTION_DAYS` | `30` | Days of per-day log files (`data/logs/YYYY-MM-DD.jsonl`, browsable in `/admin`) to keep; older are pruned at startup. `0` = forever |
| `SPOTIFLAC_ENGINE_HOME` | `/data/engine-home` (Docker) | The engine's `$HOME`. Its community session lives at `<here>/.spotiflac/community_session.json` — see [Community verification](#community-verification-captcha) |
| `WITH_SOLVER` | `1` | **Build-time.** Puts Google Chrome + Xvfb in the image so the server can pass the captcha itself. `0` builds the slim image, several hundred MB smaller, but then the session file is yours to supply |
| `TZ` | *(UTC)* | Container timezone, and so the solver's browser clock. The captcha's scoring compares it against the address the request came from, so set it to the host's zone |
| `AUTO_VERIFY` | `true` | Let the engine pass the captcha itself. Needs `WITH_SOLVER=1`; with no browser available it logs why and falls back to the manual route |
| `VERIFY_COMMAND` | *(unset)* | Override the solver invocation — a JSON array or a command line. The challenge URL is appended as the final argument |
| `VERIFY_HOLD_OPEN` | `5` | Seconds the solver keeps the browser open after passing, so the page can hand the grant back to the engine |

---

## Community verification (captcha)

Since SpotiFLAC v7.2.0 the community download endpoints sit behind a human verification step
(a Cloudflare Turnstile check) that issues a signing **session**, written to
`.spotiflac/community_session.json` under the engine's home directory. Sessions expire, and
without a valid one every download fails — usually as `browser integration is not ready`, or
a bare "all sources failed".

The server does this itself. The image ships with a browser, so all it needs is the right
clock:

```bash
cd backend
echo "TZ=Asia/Bangkok" >> .env   # the timezone your traffic appears to come from
docker compose build && docker compose up -d
```

That's the whole setup. Verification happens on demand — the first download that needs a
session solves the captcha and writes the file, taking an extra minute or so, and it renews
itself the same way when the session expires. To do it ahead of time, or to see where things
stand:

```bash
curl -H "Authorization: Bearer $API_KEY" https://your-server/downloader/verification
curl -X POST -H "Authorization: Bearer $API_KEY" https://your-server/downloader/verification
```

`POST` mints a session now (via a one-track probe, which is what triggers verification);
`?force=true` discards the current one first. The same report rides along on
`GET /downloader/status`.

`TZ` matters because a container is UTC while its traffic leaves from wherever it's hosted,
and the captcha's scoring compares the two. Set it to the zone your **egress address**
appears to be in — on a hosting provider that's the provider's region, not yours. Only the
offset really matters.

To check the solver works on a given host at all, without involving the real service:

```bash
docker compose exec backend python -m turnstile_solver.selftest
```

### From a shell on the server

On a hosting platform the service console is often the easiest way in — and the image has no
`curl`, so use these rather than hitting the HTTP endpoints. Everything runs from `/srv`:

```bash
python -m app.verify_cli --status          # is there a session, when does it expire
python -m app.verify_cli --now             # mint one now (downloads one track)
python -m app.verify_cli --now --force     # discard the current session first
python -m turnstile_solver.selftest        # can this host solve a captcha at all
python -m turnstile_solver.selftest --fingerprint   # egress address vs browser clock
```

`--fingerprint` is the one to run first on a new deployment: it names the `TZ` to set by
comparing the browser's timezone against the address your traffic actually leaves from,
which on a hosting provider is their region rather than yours.

If a solve fails, `$DATA_DIR/verify-diagnostics/` holds a screenshot, the page's DOM and a
JSON dump of its state, newest last.

**Without a browser** — `WITH_SOLVER=0`, `AUTO_VERIFY=false`, or a solver that can't run —
the engine logs the challenge URL and waits five minutes for someone to solve it. You can
also create the session elsewhere and copy it in:

1. Run the **official SpotiFLAC desktop app** on your PC and start any download. It opens
   the verification page — solve it once. That writes
   `%USERPROFILE%\.spotiflac\community_session.json` (Linux/macOS: `~/.spotiflac/`).
2. Copy that file into the same relative location under the server engine's home directory.
   It's picked up on the next download; no restart needed.
3. Repeat when it expires. `GET /downloader/verification` shows `expiresAt`.

If downloads keep failing and the session is fine, the usual cause is that the third-party
proxy APIs are temporarily down or rate-limited. Set `DEFAULT_SERVICES=qobuz,amazon` to skip
Tidal when its proxies are dead, or simply try later — the infrastructure is
community-maintained and goes down periodically.

---

## Putting it on the internet

A Caddy reverse proxy ships as a compose overlay. It terminates TLS (automatic Let's
Encrypt), rate-limits the unauthenticated pages (`/` and `/public/status` at 10 req/s per IP,
everything else 30), writes access logs separately from the app's own
(`backend/logs/caddy/access.log`), and takes uvicorn's `:8000` off the network — only 80/443
are published, with the backend still reachable at `127.0.0.1:8000` on the host for
debugging.

```bash
cd backend
echo "DOMAIN=music.example.com" >> .env   # a hostname that resolves to this server
docker compose -f docker-compose.yml -f docker-compose.public.yml up --build -d
```

Point the phone app at `https://your-domain` (no port). Without a `DOMAIN`, Caddy serves
`localhost` with a self-signed certificate — fine for a look around, but phones will reject
it, so use a real domain (a free DuckDNS name works) in production.

**On a PaaS (Zeabur, Railway, Fly…)** skip this overlay entirely — the platform terminates
TLS and routes to the container itself. You only need to set the environment variables and
mount a volume at `/data`.

If you'd rather not expose anything publicly, don't: reach the server over Tailscale or
WireGuard instead.

### Security

The backend must never be exposed unauthenticated. Use a long random `API_KEY`
(`openssl rand -hex 32`, never the placeholder), and reach the server only through the TLS
proxy above, a PaaS that terminates TLS, or a VPN. Publishing raw `:8000` to the internet
sends the API key in the clear.

---

## Backups

Everything worth keeping lives in `backend/data/`: the SQLite job DB, per-day logs, the probe
cache and health history, admin state, and the engine's session file.

```bash
./scripts/backup-data.sh          # → ./backups/instaplayer-data-<timestamp>.tar.gz
```

It skips the disposable per-job download directories and keeps the newest 14 archives
(`KEEP=N` to change). From cron, daily at 04:00:

```
0 4 * * * cd /path/to/InstaPlayer && ./scripts/backup-data.sh >> backups/backup.log 2>&1
```

Copy `backups/` off the machine if the server's disk is what you're insuring against.
Restoring is the reverse: stop the stack, untar over `backend/data/`, start it again.

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Status light red, "engine not working" | Binary missing or unrunnable — check `SPOTIFLAC_DL_BIN` and the image build |
| "browser integration is not ready" | No valid community session — see [Community verification](#community-verification-captcha) |
| "On cooldown — retrying in ~N min" | Upstream rate-limited you; the server retries automatically when it expires |
| Jobs finish with zero tracks | All configured sources failed — try different `DEFAULT_SERVICES`, or wait |
| Phone can't reach the server | Wrong address or a TLS certificate the phone won't trust (see above) |

The `/admin` dashboard is the fastest way to see what happened: day-by-day logs with search,
the health timeline, and the last job's error.
