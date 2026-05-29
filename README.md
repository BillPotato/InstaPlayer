# Music App — Offline FLAC Player

A phone-based **offline music player** (Android-first, Flutter) paired with a **self-hosted
backend**. You hand the backend a Spotify playlist/album URL; it resolves each track's ISRC,
downloads the matching lossless FLAC from hi-fi sources via [SpotiFLAC](https://github.com/spotbye/SpotiFLAC),
tags it, and fetches synced lyrics. The Flutter app browses that library, downloads tracks to
the phone, and plays them **fully offline**.

> See [the architecture plan](#architecture) and the build plan in
> `C:\Users\Bill\.claude\plans\` for the full design.

## Repository layout

```
backend/   FastAPI service that wraps SpotiFLAC (Python 3.11, Dockerized)
app/        Flutter mobile client (Android first)  — added in a later phase
```

## ⚠️ Legal / distribution note

The backend downloads tracks from third-party hi-fi services via ISRC matching, which violates
those services' Terms of Service. **Keep the download capability strictly on your own
self-hosted backend and use it for personal use only.** The Flutter client itself is a neutral
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
Flutter client  ──REST + WebSocket──►  Self-hosted backend (Docker)
  • library browser                      • FastAPI + job queue
  • just_audio playback                  • SpotiFLAC wrapper (ISRC → Tidal/Qobuz/Amazon)
  • offline FLAC store (resumable)        • Go tagger + LRCLIB lyrics
  • drift (SQLite) mirror                 • SQLite metadata + FLAC file store
```

## Security

The backend must not be exposed unauthenticated. Use the bearer `API_KEY`, and expose it over
a VPN (Tailscale/WireGuard) or a TLS reverse proxy rather than a raw open port.
