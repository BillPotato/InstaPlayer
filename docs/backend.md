# How the Backend Works

The backend is a Python web server. Its only job is to download songs from
Spotify playlists and hand them to your phone. It never keeps songs — once
your phone has the files, the backend deletes its copy.

---

## The big picture

1. Your phone says "download this Spotify playlist."
2. The backend downloads the songs using a tool called SpotiFLAC.
3. As each song finishes downloading, the backend tells your phone immediately.
4. Your phone downloads that song from the backend.
5. Once your phone has everything, it tells the backend, which deletes its copy.

That's it. The backend is a temporary middleman, not a permanent library.

---

## Files and what they do

### `config.py` — the settings file

Stores all the knobs you can turn: the API password, where to save temporary
files, which music services to try (Tidal, Qobuz, etc.), audio quality, and
how long to keep files before automatically deleting them.

These settings are read from a `.env` file or from environment variables, so
you can change them without editing code.

### `db.py` — the database connection

Sets up a connection to a SQLite database (a single file on disk). The
database only stores one thing: the status of active download jobs — whether
they're running, finished, or failed. Songs are never stored here.

### `models.py` — the database table

Defines the one and only database table: `jobs`. Each row is one download
job. It tracks:

- The Spotify URL that was requested
- Whether the job is queued, running, completed, failed, or cancelled
- How many tracks have been downloaded so far
- Which track is currently downloading
- Any error message if something went wrong

### `schemas.py` — the shapes of API messages

Defines exactly what JSON the server accepts and returns. For example, when
your phone asks to start a download it must send `{ "spotifyUrl": "..." }`.
When the server responds, it sends back the job's ID and status. These
definitions also validate the data automatically — if the URL isn't a Spotify
link, the server rejects it with a clear error before doing any work.

### `auth.py` — the password check

Every request must include a secret password (called a bearer token) in the
HTTP header. This file checks that the password matches. If it doesn't, the
request is rejected immediately. The check is done in a way that doesn't leak
the password even if an attacker measures how fast the server responds.

### `ingest.py` — reading songs and building the playlist file

After SpotiFLAC downloads a FLAC file, this file does two things:

1. **Reads the song's metadata** (title, artist, album, ISRC code, and any
   album art embedded in the file) using a library called mutagen.

2. **Fetches album art** if the FLAC has none. It tries Deezer first (looks up
   by ISRC code), then iTunes Search (looks up by title and artist). Both are
   free with no account required.

3. **Builds and updates `manifest.json`** — a file that lists every song in
   the job, with its metadata and where to find its audio and art files. Your
   phone reads this manifest to know what to download. The manifest grows as
   songs finish — song 0 appears first, then song 1, and so on, so your phone
   can start downloading before the whole playlist is ready.

### `spotiflac_adapter.py` — running the SpotiFLAC engine

The SpotiFLAC engine is what actually downloads songs from Tidal, Qobuz, and
Amazon by matching Spotify track IDs to their ISRC codes. It's a small
self-contained program (`spotiflac-dl`, built from Go source that lives in
`backend/spotiflac-go/` and baked into the Docker image — not a pip package).
This file launches it as a subprocess and watches its output.

The engine is a black box — it has no progress callback. So this file reads
everything it prints, line by line, and parses useful information out of it:
a `Track [1/12] Title — Artist` line gives both the total (`12`) and the
current track label shown on the progress bar. If the engine exits with an
error, the last line of its output is surfaced as the failure reason.

### `jobs.py` — the engine that runs everything

This is the core of the backend. When a download job starts, this file:

1. Creates a database row for the job.
2. Starts the SpotiFLAC engine in a background thread (it blocks for minutes,
   and running it directly would freeze the server).
3. Simultaneously runs a watcher every second that checks if new song files
   have appeared on disk.
4. When a new song is ready, updates the manifest and sends an instant message
   to your phone's WebSocket connection so it can start downloading right away.
5. When the job finishes (or is cancelled), cleans up.

It also handles cancellation: if your phone sends a cancel request, or if your
phone disconnects and doesn't reconnect within 20 seconds, the download is
stopped and the temporary files are deleted.

### `main.py` — the front door

This is the web server file. It defines all the URLs your phone can call:

| URL | What it does |
|-----|-------------|
| `POST /jobs` | Start a new download |
| `GET /jobs` | List recent jobs, newest first (`?limit=`, ≤200) — the dashboard's job history |
| `GET /jobs/{id}` | Check the status of a job |
| `DELETE /jobs/{id}` | Tell the server you're done — it deletes the files |
| `POST /jobs/{id}/cancel` | Stop a running download |
| `GET /jobs/{id}/manifest` | Get the list of songs in the job |
| `GET /jobs/{id}/files/{n}` | Download song number `n` |
| `GET /jobs/{id}/art/{n}` | Download the album art for song `n` |
| `WS /jobs/{id}/events` | A live connection that streams progress updates |
| `GET /downloader/status` | Is the download engine (SpotiFLAC) healthy? Cheap: engine-binary present + version, configured sources, last job outcome (`lastJob`), the currently running job's progress (`activeJob` — id/total/completed/current), the stored probe result (`lastProbe`, including `cooldownUntil` when upstream is rate-limiting), and `nextProbeAt` |
| `POST /downloader/probe` | Deep check: downloads one sample track into a throwaway dir and reports ok/failure. Answers instantly from the stored result while fresh (kept warm by a periodic probe every `PROBE_INTERVAL_MINUTES`); `?force=true` always runs live. Live runs are rejected (409) while a job is active. See `PROBE_SPOTIFY_URL` / `PROBE_TIMEOUT_SECONDS` |
| `GET /downloader/history` | Recent download-health outcomes — both hourly probes (`source: "probe"`) and real download jobs' pass/fail results (`source: "job"`), last ~200, persisted in `data/probe_history.json`. Powers the dashboard's proportional green/red timeline |
| `GET /admin/system` | Storage/health report: disk usage of the data volume, transient job-store size + active-dir count, log-file size + day count, server uptime, and a read-only summary of the effective config |
| `GET /logs` | Server log lines for one day (job lifecycle + engine output), written to a per-day file `data/logs/YYYY-MM-DD.jsonl`. `?date=YYYY-MM-DD` (default today); `?after=<lineOffset>` returns only new lines so today's tail polls cheaply. Old files are pruned after `LOG_RETENTION_DAYS` |
| `GET /logs/days` | The days that have log files, plus the server's current day — powers the dashboard's calendar and prev/next arrows |
| `GET /admin` | The admin dashboard — a single self-contained web page (no auth on the page itself; it asks for the API key and calls the endpoints above). Status light + a proportional green/red download-health timeline (probes + real jobs, with a 24h/3d/7d window), force-probe with cooldown countdown, active-download progress + cancel, a recent-jobs table (cancel/delete), a storage/health panel, and day-by-day logs with a calendar, prev/next arrows, search, level filter, and export |

It also runs two things at startup:
- **Orphan cleanup**: if the server crashed while a job was running, that job
  is stuck in "running" forever. At startup, any stuck job is marked "failed"
  so the phone stops waiting for it.
- **Reaper**: every 30 minutes, deletes any leftover files from jobs that
  finished more than 6 hours ago.

---

## How a download actually works, step by step

```
Phone:   "Download this Spotify playlist."
Server:  Creates a job (ID = abc123), returns that ID to the phone.

[Background — the SpotiFLAC engine running in a thread]
Engine:  "Track [1/10] ..."
  → server stores total=10
Engine:  finishes downloading track 0
  → server reads its metadata, fetches art, adds it to manifest.json
  → server sends "file_ready n=0" to phone over WebSocket

Phone:   receives "file_ready n=0"
Phone:   GET /jobs/abc123/files/0  → downloads the FLAC
Phone:   GET /jobs/abc123/art/0   → downloads the album art
Phone:   saves both files locally, song appears in the library

[This repeats for tracks 1, 2, 3 ... as each one finishes]

Engine:  all done
Server:  sends "status=completed" over WebSocket

Phone:   receives "completed"
Phone:   DELETE /jobs/abc123
Server:  deletes the temporary folder — backend has no copy of the songs now
```

---

## How to add a new feature

Most features follow one of these patterns:

**New setting** → add a field to `Settings` in `config.py`. It's automatically
read from the `.env` file with no other changes needed.

**New API endpoint** → add a function to `main.py` decorated with
`@app.get(...)`, `@app.post(...)`, etc. Add `dependencies=[Depends(require_auth)]`
if it should require the password.

**Change what job data is stored** → add a column to the `Job` class in
`models.py`. The migration in `db.py` will add it to the database automatically
on the next startup without wiping existing data.

**Change what the API returns** → update the relevant class in `schemas.py`.

**Change how songs are processed** → edit `ingest.py`. The `_track_entry`
function is where each song's metadata is read and art is fetched.

**Change download behaviour** → edit `jobs.py`. The `_run` method is the main
download loop; `_watch` is the watcher that fires as each song lands.
