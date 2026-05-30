# Backend — Technical Reference

The backend is a **FastAPI application** running under **Uvicorn** (an async Python web server). Its entire job is: accept a Spotify URL → run SpotiFLAC → serve the downloaded files temporarily → delete them once the device has a copy. It stores nothing permanently.

---

## File Map

```
backend/app/
├── config.py            — settings (env vars, paths, defaults)
├── db.py                — SQLAlchemy engine + session factory
├── models.py            — the Job ORM table (the only table)
├── schemas.py           — Pydantic request/response shapes
├── auth.py              — bearer-token check shared by all routes
├── ingest.py            — reads FLAC metadata, fetches art, builds the manifest
├── spotiflac_adapter.py — wraps the SpotiFLAC Python library
├── jobs.py              — the job manager (orchestrates everything)
└── main.py              — FastAPI app, routes, WebSocket, startup lifecycle
```

---

## `config.py` — Settings

```python
class Settings(BaseSettings):
    api_key: str = "change-me-in-.env"
    data_dir: Path = Path("./data")
    default_services: list[str] = ["tidal", "qobuz", "amazon", "deezer"]
    quality: str = "LOSSLESS"
    qobuz_token: str | None = None
    track_max_retries: int = 2
    job_retention_hours: float = 6.0

    @property
    def jobs_dir(self) -> Path: ...       # data/jobs/
    @property
    def database_url(self) -> str: ...    # sqlite:///data/jobs.db
```

`BaseSettings` (from `pydantic-settings`) reads values from environment variables **or** a `.env` file. The env var name is the attribute name uppercased — e.g. `API_KEY=secret` overrides `api_key`.

`get_settings()` is decorated with `@lru_cache` — it only creates the `Settings` object once for the entire process lifetime. Every call after the first returns the cached instance. This is the standard FastAPI pattern for a singleton config.

`jobs_dir` is a computed property, not a stored column. Every finished job gets its own subdirectory: `data/jobs/{job_id}/`. When the device is done, that directory is deleted.

---

## `db.py` — Database Layer

```python
engine = create_engine(
    _settings.database_url,
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
```

**Engine** is the SQLAlchemy connection pool — one global instance for the whole app. `check_same_thread=False` is required for SQLite because FastAPI's async event loop and thread-pool workers share the same engine but from different threads.

**SessionLocal** is a factory — calling `SessionLocal()` gives you a `Session` object for one unit of work. `autoflush=False` means SQL is only sent when you explicitly call `session.commit()`. `expire_on_commit=False` means after a commit, objects remain usable instead of being invalidated (important in `jobs.py` which reads the id after inserting).

**WAL mode** (`PRAGMA journal_mode=WAL`) is set at startup. WAL lets readers and writers work concurrently — one thread can read the DB while another is writing, which matters because the job watcher (reading) and status updater (writing) run simultaneously.

**`_migrate()`** is a lightweight schema migrator. SQLAlchemy's `create_all()` creates missing *tables* but ignores missing *columns* on existing tables. `_migrate()` does `PRAGMA table_info(table)` for each table, diffs that against the ORM model's columns, and issues `ALTER TABLE ... ADD COLUMN` for anything new. This lets you add a column to `models.py` without wiping the database.

**`get_session()`** is a FastAPI dependency — a generator yielding a session, used with `Depends(get_session)` in route handlers:

```python
def some_route(session: Session = Depends(get_session)):
    ...
```

FastAPI runs the code before `yield` at the start of the request, injects the session, and runs the code after `yield` (rollback/close) when the response is sent — even if an exception occurred.

---

## `models.py` — The Only Table

```python
class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str]              # 32-char hex UUID (e.g. "ab469f039689...")
    spotify_url: Mapped[str]
    preferred_source: Mapped[str | None]
    status: Mapped[str]          # "queued" | "running" | "completed" | "failed" | "cancelled"
    total: Mapped[int]           # how many tracks SpotiFLAC expects
    completed: Mapped[int]       # how many tracks are in the manifest (fetchable)
    current: Mapped[str | None]  # label of the track currently downloading
    error: Mapped[str | None]
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]
```

`Mapped[T]` is SQLAlchemy 2.x's typed column syntax. `mapped_column(...)` configures the column — index, default, etc.

The `default=_uuid` on `id` means SQLAlchemy calls `_uuid()` in Python when inserting a new row (not a SQL `DEFAULT` — it's Python-side). Same for `created_at` and `updated_at`.

`onupdate=_now` on `updated_at` means SQLAlchemy automatically calls `_now()` whenever a row is updated.

This is the **only table**. There are no track or playlist tables — songs live exclusively on the device.

---

## `schemas.py` — API Shapes

Pydantic models define what JSON goes in and out of each endpoint.

**`JobCreate`** — what the client sends to `POST /jobs`:
```python
class JobCreate(BaseModel):
    spotifyUrl: str           # validated to be a Spotify URL
    preferredSource: str | None = None
```

The `@field_validator` runs before the object is constructed. If `spotifyUrl` doesn't contain `spotify.com/` or start with `spotify:`, Pydantic raises a `ValidationError` which FastAPI converts to a 422 response automatically.

**`JobOut`** — what the server returns for `GET /jobs/{id}` and `POST /jobs`:
```python
class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    status: str
    total: int
    completed: int
    ...
```

`from_attributes=True` lets Pydantic read from a SQLAlchemy ORM object's attributes instead of requiring a dict. So you can do `JobOut.model_validate(job_orm_object)` directly.

**`Manifest` + `ManifestTrack`** — what the client gets from `GET /jobs/{id}/manifest`. This is a Pydantic representation of the `manifest.json` file on disk.

**The relationship between schemas and models:** `Job` (models.py) is the SQLAlchemy ORM — it talks to SQLite. `JobOut` (schemas.py) is the Pydantic model — it talks to the HTTP client. They're kept separate because the ORM has SQLAlchemy-specific machinery that Pydantic doesn't understand, and the API response shape might differ from the stored shape.

---

## `auth.py` — Bearer Token

```python
_bearer = HTTPBearer(auto_error=True)

def require_auth(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    settings: Settings = Depends(get_settings),
) -> None:
    if not secrets.compare_digest(credentials.credentials, settings.api_key):
        raise HTTPException(401, "Invalid API key")
```

`HTTPBearer` is a FastAPI security utility. It reads the `Authorization: Bearer <token>` header. If the header is missing, `auto_error=True` automatically returns 403. If present, it passes the token as `credentials.credentials`.

`secrets.compare_digest` does a **constant-time string comparison**. A naive `==` comparison leaks information via timing — if the first character is wrong it returns faster than if only the last character is wrong. `compare_digest` always takes the same time regardless of where the strings differ.

`require_auth` is used as a dependency on routes: `dependencies=[Depends(require_auth)]`. FastAPI calls it before the route handler. If it raises an exception, the route never runs.

---

## `ingest.py` — FLAC Parsing and Manifest Building

This file has two responsibilities: parsing FLAC metadata, and building/updating the `manifest.json` that the device fetches.

### `parse_flac(path)`

```python
def parse_flac(path: Path) -> FlacMeta:
    audio = FLAC(str(path))            # mutagen reads the file
    meta = FlacMeta(
        title=_first(audio, "title"),  # reads FLAC Vorbis comment tags
        isrc=_first(audio, "isrc"),
        ...
    )
    if audio.info and audio.info.length:
        meta.duration_ms = int(audio.info.length * 1000)
    if audio.pictures:                 # FLAC PICTURE metadata block
        pic = audio.pictures[0]
        meta.art_bytes = pic.data      # raw image bytes (JPEG or PNG)
        meta.art_mime = pic.mime
    return meta
```

`mutagen.flac.FLAC` opens the file and parses its metadata. FLAC stores tags as "Vorbis comments" — key-value pairs like `TITLE=Song Name`. `_first(audio, "title")` looks up the tag by key (case-insensitive in mutagen's implementation).

`audio.pictures` is a list of embedded `PICTURE` blocks — album art embedded directly in the FLAC file. Most are JPEG.

### `_fetch_art_online(meta)` — the fallback

When no embedded picture exists, this tries two free APIs in order:

1. **Deezer by ISRC** — `GET https://api.deezer.com/track/isrc:{isrc}` returns JSON; we pull `album.cover_xl` from it and download that image URL.
2. **iTunes Search** — `GET https://itunes.apple.com/search?term={title}+{artist}&entity=song&limit=5` returns a list of matches; we take the first result's `artworkUrl100` and replace `100x100bb` with `1200x1200bb` for full resolution.

Both use Python's standard `urllib.request` (no third-party HTTP library needed). Each request has an 8-second timeout. Any exception at any step is caught and we return `None` — this is best-effort.

### `_track_entry(job_dir, path, n)`

Called once per FLAC file. Returns a dict that becomes one entry in the manifest's `tracks` array, or `None` if the file can't be parsed (still being written by SpotiFLAC).

```python
def _track_entry(job_dir, path, n):
    try:
        meta = parse_flac(path)
    except Exception:
        return None  # file not ready — caller retries later

    if not meta.art_bytes:
        result = _fetch_art_online(meta)  # try Deezer / iTunes
        if result:
            meta.art_bytes, meta.art_mime = result

    if meta.art_bytes:
        art_path = job_dir / "art" / f"{n}.jpg"
        art_path.write_bytes(meta.art_bytes)  # sidecar file

    return {
        "n": n,              # stable index: device uses /files/{n} and /art/{n}
        "file": "...",       # relative path to the FLAC within the job dir
        "hasArt": has_art,
        "artFile": art_file, # relative path to the art sidecar, or null
        ...
    }
```

The index `n` is **stable and append-only** — once assigned, it never changes. This matters because the device might start downloading `/files/0` while tracks 1, 2, 3 are still being assigned indices. If indices shifted, the device would download the wrong file.

### `update_manifest(job_dir, spotify_url)` — the core loop

```python
def update_manifest(job_dir, spotify_url):
    with _manifest_lock:          # threading.Lock — prevents concurrent corruption
        files = scan_flacs(job_dir)
        manifest = load_manifest(job_dir) or { ... }    # load existing or start fresh
        known = {t["file"] for t in manifest["tracks"]} # already-processed files

        for path in files:
            if path in known: continue       # already processed
            entry = _track_entry(...)
            if entry is None: continue       # file not ready — skip, retry next call
            manifest["tracks"].append(entry)
            known.add(path)

        manifest["trackCount"] = len(manifest["tracks"])
        manifest.write_text(json.dumps(manifest))
        return manifest
```

This is called every second by the job watcher. It's **idempotent** — calling it multiple times is safe because `known` prevents re-processing files that are already in the manifest. The `threading.Lock` prevents the watcher and the final-pass code from corrupting the JSON file when they overlap.

---

## `spotiflac_adapter.py` — Wrapping SpotiFLAC

SpotiFLAC has no callback API. The only way to observe progress is by parsing the text it prints to stdout/stderr. This file handles both concerns.

### Progress parsing

```python
_FOUND_RE = re.compile(r"Found\s+(\d+)\s+track", re.IGNORECASE)
_TRYING_RE = re.compile(r"Trying:\s*(.+?)\s*$")
```

When SpotiFLAC prints `"Found 12 track(s)"`, we extract `12` and report it as `total`. When it prints `"Trying: Artist — Title"`, we report the track label as `current`.

### Capturing stdout and stderr

```python
class _ProgressTee(io.TextIOBase):
    def write(self, s: str) -> int:
        self._original.write(s)  # still pass through to real stdout
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self._on_line(line)  # parse each complete line
        return len(s)
```

`_ProgressTee` is a custom file-like object. `contextlib.redirect_stdout` swaps `sys.stdout` with this object for the duration of the SpotiFLAC call. Any `print()` call inside SpotiFLAC goes through `_ProgressTee.write()`, which forwards to the real stdout **and** fires the progress callback.

```python
with redirect_stdout(_ProgressTee(sys.stdout, on_line)), \
     redirect_stderr(_ProgressTee(sys.stderr, on_line)):
    SpotiFLAC(**kwargs)
```

This is done for both stdout and stderr because SpotiFLAC uses both. SpotiFLAC runs synchronously and completely blocks until done.

---

## `jobs.py` — The Job Manager

This is the most complex file. It owns the entire download lifecycle.

### State

```python
class JobManager:
    _subscribers: dict[str, set[asyncio.Queue]]  # job_id → set of WebSocket queues
    _last_event:  dict[str, dict]                # job_id → most recent event (for late subscribers)
    _tasks:       dict[str, asyncio.Task]        # job_id → running asyncio Task
    _cancel_timers: dict[str, asyncio.Task]      # job_id → pending auto-cancel timer
```

### Pub/Sub — how progress reaches WebSocket clients

```python
def subscribe(self, job_id) -> asyncio.Queue:
    queue = asyncio.Queue()
    self._subscribers[job_id].add(queue)
    if job_id in self._last_event:
        queue.put_nowait(self._last_event[job_id])  # replay last event immediately
    # cancel any pending disconnect timer
    return queue

def _publish(self, job_id, event):
    self._last_event[job_id] = event
    for queue in self._subscribers[job_id]:
        queue.put_nowait(event)             # non-blocking push to each subscriber
```

`asyncio.Queue` is an in-memory, async-safe queue. Each WebSocket connection gets its own queue via `subscribe()`. `_publish()` pushes the event dict into every connected client's queue simultaneously. The WebSocket handler loop then reads from the queue and sends the JSON over the wire.

`put_nowait()` is non-blocking — it adds to the queue without waiting. The WebSocket handler reads with `await queue.get()`, which blocks until something arrives.

When a client reconnects (e.g. after a network blip), it calls `subscribe()` again and immediately receives the last event via `queue.put_nowait(self._last_event[job_id])` — so it doesn't miss the current status.

### `submit()` — starting a job

```python
async def submit(self, spotify_url, preferred_source):
    with SessionLocal() as session:
        job = Job(spotify_url=spotify_url, ...)
        session.add(job)
        session.commit()
        job_id = job.id         # read the generated UUID before session closes

    task = asyncio.create_task(self._run(job_id))
    self._tasks[job_id] = task
    return job_id
```

`asyncio.create_task()` schedules `_run()` to execute **concurrently** — it starts soon, but not immediately. The current coroutine (`submit`) continues and returns `job_id` before `_run` has even started. This is how FastAPI can respond to `POST /jobs` instantly even though the download takes minutes.

### `_run()` — the download coroutine

```python
async def _run(self, job_id):
    loop = asyncio.get_running_loop()
    job_dir = self.settings.jobs_dir / job_id
    state = {"emitted": 0}    # how many file_ready events have been published

    self._set_status(job_id, status="running")
    progress = {"total": None, "current": None}

    watcher = asyncio.create_task(self._watch(job_id, job_dir, spotify_url, progress, state))

    try:
        await loop.run_in_executor(None, run_spotiflac, spotify_url, job_dir, ...)
        # ... handle success
    except asyncio.CancelledError:
        # ... handle cancellation
    except SpotiFlacError as exc:
        # ... handle download failure
    finally:
        self._tasks.pop(job_id, None)
```

`run_in_executor(None, run_spotiflac, ...)` is the critical line. SpotiFLAC is **blocking** — it runs synchronously for minutes. If you called it directly in the coroutine, it would freeze the entire event loop and no other request could be served.

`run_in_executor(None, ...)` offloads it to Python's default **thread pool executor**. `None` means "use the default executor". The `await` suspends this coroutine (freeing the event loop to serve other requests) and resumes only when the thread finishes. The blocking SpotiFLAC runs in a background thread; the event loop stays responsive.

`_watch()` runs **concurrently** with `run_in_executor` — it's a separate `asyncio.Task`. While SpotiFLAC is downloading in a thread, the watcher runs in the event loop (it's async, using `await asyncio.sleep(1.0)` between iterations).

### `_watch()` — the progress watcher

```python
async def _watch(self, job_id, job_dir, spotify_url, progress, state):
    loop = asyncio.get_running_loop()
    try:
        while True:
            if len(scan_flacs(job_dir)) > state["emitted"]:
                manifest = await loop.run_in_executor(None, update_manifest, ...)
                new_count = manifest["trackCount"]
                for n in range(state["emitted"], new_count):
                    self._publish(job_id, {"type": "file_ready", "jobId": job_id, "n": n})
                state["emitted"] = new_count

            self._set_status(job_id, completed=state["emitted"], ...)
            await asyncio.sleep(1.0)
    except asyncio.CancelledError:
        return
```

Every second it checks if new FLAC files landed in `job_dir`. When they do, it calls `update_manifest()` (also offloaded to a thread via `run_in_executor`, because mutagen's file parsing and disk writes would block the event loop). For each newly-added track it publishes a `file_ready` event so the device can start downloading immediately.

`state["emitted"]` is a **shared mutable dict** between `_run` and `_watch`. It's how `_run` knows, after cancelling the watcher, how many `file_ready` events were already sent — so it can emit the stragglers in the final pass.

`await asyncio.sleep(1.0)` is the yield point. This is where `asyncio.CancelledError` is injected when `task.cancel()` is called — it arrives at the next `await`.

### `_set_status()` — updating the DB and publishing

```python
def _set_status(self, job_id, **fields):
    with SessionLocal() as session:
        job = session.get(Job, job_id)
        for key, value in fields.items():
            setattr(job, key, value)
        session.commit()
        event = {"type": "status", "jobId": job.id, "status": job.status, ...}
    self._publish(job_id, event)
    return event
```

Every status change goes to SQLite **and** to the WebSocket pub/sub simultaneously. This means:
- WebSocket clients get the update immediately (in-memory, sub-millisecond)
- REST polling clients (`GET /jobs/{id}`) get it from SQLite on the next poll

### Cancellation

```python
def cancel_job(self, job_id):
    task = self._tasks.get(job_id)
    if task and not task.done():
        task.cancel()   # injects CancelledError at the next await in _run/_watch
```

In `_run`'s `except asyncio.CancelledError:` handler:

```python
except asyncio.CancelledError:
    watcher.cancel()
    await watcher             # wait for watcher to finish its cleanup
    shutil.rmtree(job_dir)    # delete all temp files
    self._set_status(job_id, status="cancelled")
    # delete DB row
    # does NOT re-raise — task exits cleanly
```

Not re-raising `CancelledError` is intentional: we want the cleanup code to run to completion, so we treat cancellation as a normal exit path rather than an abrupt one.

### Disconnect auto-cancel

```python
def on_client_disconnected(self, job_id):
    async def _delayed():
        await asyncio.sleep(20)
        self.cancel_job(job_id)
    self._cancel_timers[job_id] = asyncio.create_task(_delayed())
```

When a WebSocket disconnects, a 20-second timer starts. If a client reconnects within 20 seconds (calls `subscribe()`), the timer is cancelled. If nobody reconnects, the job is cancelled automatically — no orphaned downloads consuming bandwidth.

### Reaper

```python
async def reaper(self):
    while True:
        await asyncio.sleep(1800)  # every 30 minutes
        self._reap_once()

def _reap_once(self):
    cutoff = time.time() - self.settings.job_retention_hours * 3600
    for child in jobs_dir.iterdir():
        if child.stat().st_mtime < cutoff:
            shutil.rmtree(child)
            # delete DB row
```

The reaper is a long-running async task (started in `lifespan`). It deletes any job directory whose files haven't been touched for longer than `job_retention_hours` (default 6 hours). This is the safety net for jobs where the device never called `DELETE /jobs/{id}` — e.g., if the device crashed after downloading everything.

---

## `main.py` — Routes and Startup

### Lifespan

```python
@asynccontextmanager
async def lifespan(app):
    init_db()                        # create/migrate schema
    _fail_orphaned_jobs()            # mark stuck "running" jobs as "failed"
    reaper = asyncio.create_task(get_job_manager().reaper())
    try:
        yield                        # server is alive here
    finally:
        reaper.cancel()              # clean shutdown
```

`@asynccontextmanager` + `yield` is the FastAPI pattern for startup/shutdown code. Everything before `yield` runs at startup; everything after `yield` (the `finally`) runs at shutdown.

### Route Table

| Method | Path | Auth | What it does |
|--------|------|------|--------------|
| `GET` | `/health` | No | Returns `{"status": "ok"}` — used by Docker health checks |
| `POST` | `/jobs` | Yes | Creates a job, starts the download, returns `JobOut` |
| `GET` | `/jobs/{id}` | Yes | Returns current job status — used by the polling fallback |
| `DELETE` | `/jobs/{id}` | Yes | Device calls this when done — deletes files + DB row |
| `POST` | `/jobs/{id}/cancel` | Yes | Cancels a running download |
| `GET` | `/jobs/{id}/manifest` | Yes | Returns the manifest JSON (playlist metadata) |
| `GET` | `/jobs/{id}/files/{n}` | Yes | Serves the FLAC file at index `n` (supports `Range:`) |
| `GET` | `/jobs/{id}/art/{n}` | Yes | Serves the art sidecar at index `n` |
| `WS` | `/jobs/{id}/events` | Token in query string | Streams progress events |

### The WebSocket handler

```python
@app.websocket("/jobs/{job_id}/events")
async def job_events(websocket, job_id, settings, manager):
    token = websocket.query_params.get("token")
    if token != settings.api_key:
        await websocket.close(code=4401)
        return

    await websocket.accept()
    queue = manager.subscribe(job_id)    # get a personal event queue
    try:
        while True:
            event = await queue.get()    # blocks until an event arrives
            await websocket.send_json(event)
            if event.get("status") in {"completed", "failed", "cancelled"}:
                break                    # terminal event — close gracefully
    except WebSocketDisconnect:
        manager.on_client_disconnected(job_id)  # start 20s cancel timer
    finally:
        manager.unsubscribe(job_id, queue)
        await websocket.close()
```

WebSocket auth can't use HTTP headers (the browser WebSocket API doesn't support them), so the token goes in the query string: `ws://host/jobs/{id}/events?token=secret`.

`await queue.get()` suspends the coroutine (freeing the event loop) until `_publish()` puts something in the queue. This means no CPU is used between events — no polling on the server side.

### Path traversal prevention

```python
def _safe_job(job_id):
    if not job_id.isalnum():  # UUID hex — only letters and digits
        raise HTTPException(400, "Invalid job id")
    return job_id

def _safe_path(job_dir, relative):
    base = job_dir.resolve()
    candidate = (base / relative).resolve()
    if base not in candidate.parents and base != candidate:
        raise HTTPException(400, "Invalid path")
    return candidate
```

`_safe_job` prevents a URL like `/jobs/../../../etc/passwd/cancel` from doing path traversal — a UUID hex only contains `[0-9a-f]` so anything else is rejected.

`_safe_path` resolves both paths to absolute and verifies the candidate is actually inside `job_dir`. `Path.resolve()` expands `..` so `(job_dir / "../../etc").resolve()` would land outside `job_dir` and be rejected.

---

## Data Flow

```
POST /jobs
  │
  └─► JobManager.submit()
        │  creates Job row (status=queued)
        │  asyncio.create_task(_run)   ← starts background coroutine
        └─► returns job_id instantly

_run() [background coroutine]
  │  sets status=running
  │  creates _watch() task
  │  run_in_executor(run_spotiflac)   ← blocks a THREAD, not the event loop
  │                    │
  │                    │  SpotiFLAC downloads FLACs to jobs/{id}/
  │                    │  prints "Found N tracks", "Trying: ..."
  │                    │
  │  _watch() [concurrent async task, runs every 1s]
  │    scan_flacs() → new files?
  │    run_in_executor(update_manifest) ← parses FLAC tags, fetches art online
  │    _publish(file_ready{n})           ← device can start downloading now
  │    _set_status(completed=N)          ← WebSocket clients see progress bar update
  │
  │  SpotiFLAC finishes
  │  watcher cancelled
  │  final update_manifest pass
  │  _set_status(completed, status=completed)
  │
  └─► job dir retained on disk until device fetches everything

GET /jobs/{id}/manifest  ← device reads the track list
GET /jobs/{id}/files/{n} ← device downloads each FLAC (Range: header supported)
GET /jobs/{id}/art/{n}   ← device downloads each art file

DELETE /jobs/{id}        ← device signals "I have everything"
  └─► shutil.rmtree(job_dir)
      delete DB row
```
