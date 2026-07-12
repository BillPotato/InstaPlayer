import * as SQLite from 'expo-sqlite';

const MIGRATIONS = [
  // v1 — initial schema
  `
  CREATE TABLE tracks (
    id            TEXT PRIMARY KEY,
    title         TEXT NOT NULL,
    artist        TEXT NOT NULL,
    album         TEXT NOT NULL,
    album_artist  TEXT NOT NULL,
    track_number  INTEGER,
    duration_ms   INTEGER,
    isrc          TEXT,
    quality       TEXT,
    mime          TEXT NOT NULL DEFAULT 'audio/flac',
    file_size     INTEGER NOT NULL DEFAULT 0,
    file_path     TEXT NOT NULL,
    art_path      TEXT,
    lyrics        TEXT,
    source_url    TEXT,
    created_at    INTEGER NOT NULL
  );
  CREATE INDEX idx_tracks_album ON tracks(album_artist, album);
  CREATE INDEX idx_tracks_artist ON tracks(artist);
  CREATE INDEX idx_tracks_added ON tracks(created_at DESC);

  CREATE TABLE playlists (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
  );
  CREATE TABLE playlist_tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    playlist_id TEXT NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
    track_id    TEXT NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    position    INTEGER NOT NULL
  );
  CREATE INDEX idx_pt_playlist ON playlist_tracks(playlist_id, position);

  CREATE TABLE play_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    track_id  TEXT NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    played_at INTEGER NOT NULL
  );
  CREATE INDEX idx_history_time ON play_history(played_at DESC);

  CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);

  CREATE TABLE import_jobs (
    id TEXT PRIMARY KEY,
    source_url TEXT NOT NULL,
    name TEXT,
    status TEXT NOT NULL,
    backend_status TEXT,
    total INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
  );
  CREATE TABLE import_tracks (
    job_id  TEXT NOT NULL REFERENCES import_jobs(id) ON DELETE CASCADE,
    n       INTEGER NOT NULL,
    track_id TEXT,
    state   TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (job_id, n)
  );
  `,
];

let db = null;

export async function openDb() {
  if (db) return db;
  db = await SQLite.openDatabaseAsync('instaplayer.db');
  await db.execAsync('PRAGMA journal_mode = WAL;');
  await db.execAsync('PRAGMA foreign_keys = ON;');
  const row = await db.getFirstAsync('PRAGMA user_version');
  let version = row?.user_version ?? 0;
  while (version < MIGRATIONS.length) {
    const nextVersion = version + 1;
    await db.withExclusiveTransactionAsync(async (tx) => {
      await tx.execAsync(MIGRATIONS[version]);
      await tx.execAsync(`PRAGMA user_version = ${nextVersion}`);
    });
    version = nextVersion;
  }
  return db;
}

export function getDb() {
  if (!db) throw new Error('Database not opened yet');
  return db;
}
