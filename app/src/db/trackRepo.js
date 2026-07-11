import { getDb } from './db';

function escapeLike(q) {
  return q.replace(/[\\%_]/g, (c) => `\\${c}`);
}

export async function insertTrack(t) {
  await getDb().runAsync(
    `INSERT INTO tracks (id, title, artist, album, album_artist, track_number, duration_ms,
       isrc, quality, mime, file_size, file_path, art_path, lyrics, source_url, created_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    t.id, t.title, t.artist, t.album, t.albumArtist, t.trackNumber ?? null,
    t.durationMs ?? null, t.isrc ?? null, t.quality ?? null, t.mime || 'audio/flac',
    t.fileSize || 0, t.filePath, t.artPath ?? null, t.lyrics ?? null,
    t.sourceUrl ?? null, Date.now()
  );
}

export async function getTrack(id) {
  return getDb().getFirstAsync('SELECT * FROM tracks WHERE id = ?', id);
}

export async function tracksByIds(ids) {
  if (!ids.length) return [];
  const placeholders = ids.map(() => '?').join(',');
  const rows = await getDb().getAllAsync(
    `SELECT * FROM tracks WHERE id IN (${placeholders})`, ...ids
  );
  const byId = new Map(rows.map((r) => [r.id, r]));
  return ids.map((id) => byId.get(id)).filter(Boolean);
}

export async function allTracks() {
  return getDb().getAllAsync(
    'SELECT * FROM tracks ORDER BY title COLLATE NOCASE, artist COLLATE NOCASE'
  );
}

export async function recentlyAdded(limit = 20) {
  return getDb().getAllAsync('SELECT * FROM tracks ORDER BY created_at DESC LIMIT ?', limit);
}

export async function searchTracks(q, limit = 50) {
  const like = `%${escapeLike(q)}%`;
  return getDb().getAllAsync(
    `SELECT * FROM tracks
     WHERE title LIKE ? ESCAPE '\\' OR artist LIKE ? ESCAPE '\\' OR album LIKE ? ESCAPE '\\'
     ORDER BY title COLLATE NOCASE LIMIT ?`,
    like, like, like, limit
  );
}

export async function albums() {
  return getDb().getAllAsync(
    `SELECT album, album_artist,
            COUNT(*) AS track_count,
            SUM(duration_ms) AS total_ms,
            MIN(art_path) AS art_path
     FROM tracks
     GROUP BY album_artist, album
     ORDER BY album COLLATE NOCASE`
  );
}

export async function albumTracks(albumArtist, album) {
  return getDb().getAllAsync(
    `SELECT * FROM tracks WHERE album_artist = ? AND album = ?
     ORDER BY track_number IS NULL, track_number, title COLLATE NOCASE`,
    albumArtist, album
  );
}

export async function artists() {
  return getDb().getAllAsync(
    `SELECT artist,
            COUNT(*) AS track_count,
            COUNT(DISTINCT album) AS album_count,
            MIN(art_path) AS art_path
     FROM tracks
     GROUP BY artist
     ORDER BY artist COLLATE NOCASE`
  );
}

export async function artistTracks(artist) {
  return getDb().getAllAsync(
    `SELECT * FROM tracks WHERE artist = ?
     ORDER BY album COLLATE NOCASE, track_number IS NULL, track_number, title COLLATE NOCASE`,
    artist
  );
}

export async function deleteTrackRow(id) {
  await getDb().runAsync('DELETE FROM tracks WHERE id = ?', id);
}

export async function storageStats() {
  return getDb().getFirstAsync(
    'SELECT COUNT(*) AS track_count, COALESCE(SUM(file_size), 0) AS total_bytes FROM tracks'
  );
}

export async function tracksBySize() {
  return getDb().getAllAsync('SELECT * FROM tracks ORDER BY file_size DESC');
}

export async function findDuplicate(title, artist, fileSize) {
  return getDb().getFirstAsync(
    `SELECT id FROM tracks
     WHERE file_size = ? AND title = ? COLLATE NOCASE AND artist = ? COLLATE NOCASE
     LIMIT 1`,
    fileSize, title, artist
  );
}

export async function setDurationMs(id, durationMs) {
  await getDb().runAsync('UPDATE tracks SET duration_ms = ? WHERE id = ?', durationMs, id);
}

export async function findByIsrc(isrc) {
  if (!isrc) return null;
  return getDb().getFirstAsync('SELECT * FROM tracks WHERE isrc = ? LIMIT 1', isrc);
}
