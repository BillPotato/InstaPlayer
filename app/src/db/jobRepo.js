import { getDb } from './db';

export async function insertJob(job) {
  const now = Date.now();
  await getDb().runAsync(
    `INSERT INTO import_jobs (id, source_url, name, status, backend_status, total, error, created_at, updated_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    job.id, job.sourceUrl, job.name ?? null, job.status, job.backendStatus ?? null,
    job.total ?? 0, job.error ?? null, now, now
  );
}

export async function updateJob(id, fields) {
  const sets = [];
  const args = [];
  for (const [col, key] of [
    ['name', 'name'], ['status', 'status'], ['backend_status', 'backendStatus'],
    ['total', 'total'], ['error', 'error'],
  ]) {
    if (key in fields) {
      sets.push(`${col} = ?`);
      args.push(fields[key]);
    }
  }
  if (!sets.length) return;
  sets.push('updated_at = ?');
  args.push(Date.now(), id);
  await getDb().runAsync(`UPDATE import_jobs SET ${sets.join(', ')} WHERE id = ?`, ...args);
}

export async function nonTerminalJobs() {
  return getDb().getAllAsync(
    "SELECT * FROM import_jobs WHERE status NOT IN ('done', 'failed') ORDER BY created_at"
  );
}

export async function deleteJobRow(id) {
  await getDb().runAsync('DELETE FROM import_jobs WHERE id = ?', id);
}

export async function upsertImportTrack(jobId, n) {
  await getDb().runAsync(
    'INSERT OR IGNORE INTO import_tracks (job_id, n, state) VALUES (?, ?, ?)', jobId, n, 'pending'
  );
}

export async function setImportTrackState(jobId, n, state, trackId = null) {
  await getDb().runAsync(
    'UPDATE import_tracks SET state = ?, track_id = COALESCE(?, track_id) WHERE job_id = ? AND n = ?',
    state, trackId, jobId, n
  );
}

export async function bumpImportTrackAttempts(jobId, n) {
  await getDb().runAsync(
    'UPDATE import_tracks SET attempts = attempts + 1 WHERE job_id = ? AND n = ?', jobId, n
  );
}

export async function nextPendingImportTrack(jobId) {
  return getDb().getFirstAsync(
    "SELECT * FROM import_tracks WHERE job_id = ? AND state IN ('pending', 'downloading') ORDER BY n LIMIT 1",
    jobId
  );
}

export async function importTrackCounts(jobId) {
  return getDb().getFirstAsync(
    `SELECT COUNT(*) AS total,
            SUM(CASE WHEN state = 'done' THEN 1 ELSE 0 END) AS done,
            SUM(CASE WHEN state = 'failed' THEN 1 ELSE 0 END) AS failed
     FROM import_tracks WHERE job_id = ?`,
    jobId
  );
}
