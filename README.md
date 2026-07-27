# InstaPlayer

Your music, downloaded in lossless quality and playable offline — no subscription, no
streaming, no ads.

InstaPlayer has two halves: a **phone app** that stores and plays your library, and a
**small server you run yourself** that does the downloading. You paste a Spotify playlist
link, the server finds each track in lossless FLAC, and your phone pulls the songs down as
they finish. After that the music is yours — it plays with no internet at all.

```
   Spotify link  ─►  your server  ─►  your phone  ─►  offline forever
                    finds the FLACs   keeps the library
```

## What you get

- **Real lossless audio** — FLAC from hi-fi sources, matched by each track's ISRC, tagged
  with artwork and synced lyrics.
- **Genuinely offline** — the phone owns the whole library. Airplane mode changes nothing.
- **A player, not a store** — Spotify-style home, search and library, playlists, sleep
  timer, lock-screen controls.
- **Your server, your rules** — nothing is kept on the server; it deletes each song once
  your phone has it.

## Getting started

**1. Start the server** (Docker, on a machine that stays on):

```bash
cd backend
cp .env.example .env      # set API_KEY to a long random string
docker compose up --build
```

It's now at `http://localhost:8000`. Open that in a browser and you'll see a status page
telling you whether downloads are working.

**2. Install the app** on your phone — see [app/README.md](app/README.md).

**3. Connect them.** In the app's Settings, enter your server's address and the same
`API_KEY`. Then open Import, paste a Spotify playlist or album link, and start.

That's it. Songs appear in your library as they arrive.

## Two pages that come with the server

| Page | Who it's for |
|---|---|
| `/` | Anyone — is the server working, what's downloading, recent reliability |
| `/admin` | You — force a health check, read logs, cancel jobs, post a notice on `/` |

`/admin` asks for your `API_KEY` the first time and remembers it in the browser.

## Documentation

- **[Self-hosting guide](docs/self-hosting.md)** — configuration reference, putting the
  server on the internet safely, backups, troubleshooting
- **[How the backend works](docs/backend.md)** — plain-language tour of the code
- **[Android builds](docs/android-deployment.md)** — building and installing the APK
- **[App setup](app/README.md)** — running the React Native client in development

## A note on what this is

The server downloads from third-party hi-fi services, which is against those services'
terms. Keep it to your own machine and your own listening. The phone app itself is just a
media player — it contains no downloader and only talks to a server you supply.

## Repository layout

```
app/        React Native (Expo) mobile client
backend/    FastAPI server + the SpotiFLAC download engine, Dockerized
docs/       Guides and technical reference
scripts/    Maintenance helpers (backups, engine updates)
```
