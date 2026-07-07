# InstaPlayer — React Native client

Offline-first music player (Expo SDK 56, plain JavaScript, expo-router). Connects to the
self-hosted backend in `../backend`, downloads FLACs to the device, and plays them fully
offline with lock-screen controls, playlists, synced lyrics, sleep timer and more.

## Prerequisites (Windows)

1. **Node 20+** (`node -v`).
2. **JDK 17** — Temurin 17 (`winget install EclipseAdoptium.Temurin.17.JDK`). Gradle 9 refuses
   to run on JDK 8. Make sure `JAVA_HOME` points at it in a fresh terminal (`java -version`).
3. **Android SDK** — via Android Studio or cmdline-tools (already present at
   `%LOCALAPPDATA%\Android\Sdk` on this machine). An emulator AVD or a physical device with
   USB debugging.

## Run (development)

```powershell
cd app
npm install
npx expo run:android     # prebuilds android/, compiles, installs, starts Metro
```

`android/` and `ios/` are generated (Continuous Native Generation) and gitignored —
`npx expo prebuild --clean` recreates them from `app.json` at any time.

- **Emulator** reaches a backend on this PC at `http://10.0.2.2:8000`.
- **Physical device** uses your PC's LAN IP (cleartext HTTP is enabled via
  `expo-build-properties` for LAN/VPN use).
- Release build: `npx expo run:android --variant release`.

## Source layout (`src/`)

```
app/            expo-router routes
  (tabs)/       Home · Search · Library (albums/artists/playlists/songs + details)
  player.js     full-screen player (modal) — lyrics, speed, sleep timer, queue
  queue.js      queue view: drag to reorder, tap to jump, swipe X to remove
  import.js     "Paste a link" → server download job with live progress
  setup.js      first-run server setup (skippable)
  settings/     server / appearance / storage / about
api/            fetch client (Bearer auth), jobs endpoints, WebSocket w/ fast reconnect
db/             expo-sqlite: schema+migrations, track/playlist/history/job repos
downloads/      importManager (job state machine), file paths, .part downloads
player/         playerService (expo-audio engine), playerStore (zustand), queue logic
lyrics/         LRC parser (synced + plain)
components/     TrackRow, MiniPlayer, SheetMenu, LyricsView, …
stores/         settings (secure-store backed), library invalidation, import progress
theme/          dark/light palettes + accent colors
```

## Key design decisions

- **Playback engine**: one `expo-audio` `AudioPlayer` + a JS-managed queue
  (`src/player/playerService.js`). expo-audio's `AudioPlaylist` would give native gapless
  playback, but in SDK 56 only a plain `AudioPlayer` can drive the lock-screen media session
  (playlist support is merged upstream but unreleased — expo/expo#46020). When it ships,
  swap the internals of `playerService` and keep the public API.
  Note: expo-audio's Android media session currently exposes play/pause + seek on the
  notification (no next/prev buttons) — same upstream limitation.
- **The phone owns the library.** The backend is a transient middleman: `POST /jobs` →
  WebSocket `file_ready` events → pull FLAC+art with Range-resumable downloads → `DELETE` the
  job. The backend auto-cancels a job if no WebSocket subscriber is attached for ~20 s, so the
  import screen keeps the socket alive, reconnects eagerly (1/2/4 s backoff), and asks the user
  to keep the app open. Crash recovery re-attaches or drains on next launch; saved tracks
  always survive.
- **Secrets** (server URL + API key) live in the device keystore via `expo-secure-store`;
  everything else in SQLite.

## Store publishing checklist

- UI contains no third-party music-service branding; the import flow is a generic
  "paste a link" for the user's own server (same model as Subsonic/Jellyfin clients).
- Android 13+ `POST_NOTIFICATIONS` runtime permission is requested at first playback;
  the expo-audio plugin adds the `mediaPlayback` foreground service.
- Data Safety: no data collected or shared (see in-app About → Privacy).
- Before submitting: set a unique `android.package` (currently `com.instaplayer.app`),
  provide a privacy policy URL, and build an AAB (`eas build -p android` or Gradle
  `bundleRelease`).
