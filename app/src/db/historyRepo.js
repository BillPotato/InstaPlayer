import { getDb } from './db';

export async function logPlay(trackId) {
  await getDb().runAsync(
    'INSERT INTO play_history (track_id, played_at) VALUES (?, ?)', trackId, Date.now()
  );
  // Cap history growth; nobody needs more than a few thousand rows.
  await getDb().runAsync(
    `DELETE FROM play_history WHERE id NOT IN
     (SELECT id FROM play_history ORDER BY played_at DESC LIMIT 5000)`
  );
}

export async function recentlyPlayed(limit = 20) {
  return getDb().getAllAsync(
    `SELECT t.*, MAX(h.played_at) AS last_played
     FROM play_history h JOIN tracks t ON t.id = h.track_id
     GROUP BY h.track_id
     ORDER BY last_played DESC
     LIMIT ?`,
    limit
  );
}
