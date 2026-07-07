import { getDb } from './db';
import { randomId } from '../utils/uuid';

export async function createPlaylist(name) {
  const id = randomId();
  const now = Date.now();
  await getDb().runAsync(
    'INSERT INTO playlists (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)',
    id, name, now, now
  );
  return id;
}

export async function renamePlaylist(id, name) {
  await getDb().runAsync(
    'UPDATE playlists SET name = ?, updated_at = ? WHERE id = ?', name, Date.now(), id
  );
}

export async function deletePlaylist(id) {
  await getDb().runAsync('DELETE FROM playlists WHERE id = ?', id);
}

export async function getPlaylist(id) {
  return getDb().getFirstAsync('SELECT * FROM playlists WHERE id = ?', id);
}

export async function allPlaylists() {
  return getDb().getAllAsync(
    `SELECT p.*,
            (SELECT COUNT(*) FROM playlist_tracks pt WHERE pt.playlist_id = p.id) AS track_count,
            (SELECT t.art_path FROM playlist_tracks pt JOIN tracks t ON t.id = pt.track_id
             WHERE pt.playlist_id = p.id AND t.art_path IS NOT NULL
             ORDER BY pt.position LIMIT 1) AS art_path
     FROM playlists p
     ORDER BY p.updated_at DESC`
  );
}

export async function playlistTracks(playlistId) {
  return getDb().getAllAsync(
    `SELECT t.*, pt.id AS entry_id, pt.position
     FROM playlist_tracks pt JOIN tracks t ON t.id = pt.track_id
     WHERE pt.playlist_id = ?
     ORDER BY pt.position`,
    playlistId
  );
}

export async function addTracksToPlaylist(playlistId, trackIds) {
  const db = getDb();
  await db.withExclusiveTransactionAsync(async (tx) => {
    const row = await tx.getFirstAsync(
      'SELECT COALESCE(MAX(position), -1) AS max_pos FROM playlist_tracks WHERE playlist_id = ?',
      playlistId
    );
    let pos = (row?.max_pos ?? -1) + 1;
    for (const trackId of trackIds) {
      await tx.runAsync(
        'INSERT INTO playlist_tracks (playlist_id, track_id, position) VALUES (?, ?, ?)',
        playlistId, trackId, pos
      );
      pos += 1;
    }
    await tx.runAsync('UPDATE playlists SET updated_at = ? WHERE id = ?', Date.now(), playlistId);
  });
}

export async function removePlaylistEntry(playlistId, entryId) {
  await getDb().runAsync(
    'DELETE FROM playlist_tracks WHERE id = ? AND playlist_id = ?', entryId, playlistId
  );
  await reindexPositions(playlistId);
}

export async function reorderPlaylist(playlistId, fromIndex, toIndex) {
  const db = getDb();
  await db.withExclusiveTransactionAsync(async (tx) => {
    const rows = await tx.getAllAsync(
      'SELECT id FROM playlist_tracks WHERE playlist_id = ? ORDER BY position', playlistId
    );
    const ids = rows.map((r) => r.id);
    if (fromIndex < 0 || fromIndex >= ids.length || toIndex < 0 || toIndex >= ids.length) return;
    const [moved] = ids.splice(fromIndex, 1);
    ids.splice(toIndex, 0, moved);
    for (let i = 0; i < ids.length; i += 1) {
      await tx.runAsync('UPDATE playlist_tracks SET position = ? WHERE id = ?', i, ids[i]);
    }
    await tx.runAsync('UPDATE playlists SET updated_at = ? WHERE id = ?', Date.now(), playlistId);
  });
}

async function reindexPositions(playlistId) {
  const db = getDb();
  await db.withExclusiveTransactionAsync(async (tx) => {
    const rows = await tx.getAllAsync(
      'SELECT id FROM playlist_tracks WHERE playlist_id = ? ORDER BY position', playlistId
    );
    for (let i = 0; i < rows.length; i += 1) {
      await tx.runAsync('UPDATE playlist_tracks SET position = ? WHERE id = ?', i, rows[i].id);
    }
  });
}
