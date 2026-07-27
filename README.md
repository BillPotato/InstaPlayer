# InstaPlayer

Self-hosted music downloader and player wrapped around [SpotiFLAC](https://github.com/spotbye/SpotiFLAC). Download free music from providers like Amazon, Tidal and Qobuz!

InstaPlayer has two halves: a **mobile apk** that stores and plays your library, and a
**download engine** that does the downloading. You paste a Spotify playlist
link, the server finds each track in lossless FLAC, and your phone pulls the songs down as
they finish.

```
   Spotify link  ─►  download engine  ─►  your phone ─► enjoy
```

## What you get

- **Real lossless audio** with metadata and artwork
- **Offline playability** because songs are stored on your phone
- **Music player with QoL features** Spotify-style app with search, sleep timer, lock-screen controls
- **Your own server** you can self-host the server for your friend/family to use

## Getting started

**1. Start the server** (Docker, on a machine that stays on):

```bash
cd backend
cp .env.example .env      # set API_KEY to a long random string
docker compose up --build
```

It's now at `http://localhost:8000`. Open that in a browser and you'll see a status page
telling you whether downloads are working.

**2. Install the app** on your phone. See [app/README.md](app/README.md).

**3. Connect them.** In the app's Settings, enter your server's address and the same
`API_KEY`. Then open Import, paste a Spotify playlist or album link, and start.

## Two routes that come with the server

| Page | Who it's for |
|---|---|
| `/` | For guests: is the server working, what's downloading, recent reliability |
| `/admin` | For admin: a health check, read logs, cancel jobs, post announcements |

## Documentation

- **[Self-hosting guide](docs/self-hosting.md)** - configuration reference, putting the
  server on the internet safely, backups, troubleshooting
- **[How the backend works](docs/backend.md)** - plain-language tour of the code
- **[Android builds](docs/android-deployment.md)** - building and installing the APK
- **[App setup](app/README.md)** - running the React Native client in development

## Repository layout

```
app/        React Native (Expo) mobile client
backend/    FastAPI server + the SpotiFLAC download engine, Dockerized
docs/       Guides and technical reference
scripts/    Maintenance helpers (backups, engine updates)
```
