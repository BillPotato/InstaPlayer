import { AppState } from 'react-native';
import { File } from 'expo-file-system';
import * as jobsApi from '../api/jobs';
import { authHeaders, HttpError } from '../api/client';
import { JobEventSocket } from '../api/ws';
import * as jobRepo from '../db/jobRepo';
import { insertTrack } from '../db/trackRepo';
import { randomId } from '../utils/uuid';
import { patchImport, useImportStore } from '../stores/importStore';
import { bumpLibrary } from '../stores/libraryStore';
import { ensureDirs, trackFile, partFile, artFile, sweepPartFiles } from './paths';

// One import job at a time. The backend deletes a job's files if no
// WebSocket subscriber is attached for ~20s, so the socket stays open for
// the whole job and reconnects eagerly (see JobEventSocket).

const MAX_ATTEMPTS = 3;
const RETRY_DELAY_MS = [2000, 5000, 15000];
const PARALLEL_PULLS = 3;

let current = null;
let appStateSub = null;

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export function initImportManager() {
  if (!appStateSub) {
    appStateSub = AppState.addEventListener('change', (state) => {
      if (state === 'active') current?.socket?.kick();
    });
  }
}

export function isImporting() {
  return current != null;
}

export async function startImport(sourceUrl, preferredSource, quality) {
  if (current) throw new Error('An import is already running');
  ensureDirs();
  useImportStore.getState().reset();
  patchImport({ phase: 'creating', sourceUrl });
  let job;
  try {
    job = await jobsApi.createJob(sourceUrl, preferredSource, quality);
  } catch (err) {
    patchImport({ phase: 'failed', error: err.message });
    throw err;
  }
  await jobRepo.insertJob({ id: job.id, sourceUrl, status: 'active' });
  attach(job.id, sourceUrl);
  return job.id;
}

function attach(jobId, sourceUrl) {
  current = {
    jobId,
    sourceUrl,
    manifest: null,
    socket: null,
    pumping: false,
    terminalStatus: null,
    inFlight: new Map(), // n -> in-progress download promise
  };
  patchImport({ jobId, sourceUrl, phase: 'active' });

  const socket = new JobEventSocket(jobId, {
    onEvent: (event) => handleEvent(jobId, event),
    onConnected: () => patchImport({ connected: true }),
    onDisconnected: () => patchImport({ connected: false }),
  });
  current.socket = socket;
  socket.open();
}

async function handleEvent(jobId, event) {
  if (!current || current.jobId !== jobId) return;
  try {
    if (event.type === 'file_ready') {
      await ensureManifest(event.n + 1);
      pump();
    } else if (event.type === 'status') {
      patchImport({
        backendStatus: event.status,
        total: event.total || useImportStore.getState().total,
        backendCompleted: event.completed ?? 0,
        currentLabel: event.current || null,
      });
      await jobRepo.updateJob(jobId, {
        backendStatus: event.status,
        total: event.total || 0,
        error: event.error ?? null,
      });
      // The job may have been finalized/replaced during the await above.
      if (!current || current.jobId !== jobId) return;
      if (['completed', 'failed', 'cancelled'].includes(event.status)) {
        current.terminalStatus = event.status;
        current.backendError = event.error || null;
        patchImport({ phase: 'draining' });
        // Pick up any manifest rows we never got file_ready events for.
        await ensureManifest(Infinity);
        pump();
      }
    }
  } catch (err) {
    console.warn('import event handling failed', err);
  }
}

// Make sure the cached manifest covers at least `minCount` tracks and that
// an import_tracks row exists for every known track. The backend manifest is
// append-only with stable indices, so refetching is always safe.
async function ensureManifest(minCount) {
  if (!current) return;
  const have = current.manifest?.tracks?.length ?? 0;
  if (have >= minCount && Number.isFinite(minCount)) return;
  try {
    const manifest = await jobsApi.getManifest(current.jobId);
    current.manifest = manifest;
    patchImport({ name: manifest.name || null });
    await jobRepo.updateJob(current.jobId, { name: manifest.name || null });
    for (const t of manifest.tracks) {
      await jobRepo.upsertImportTrack(current.jobId, t.n);
    }
  } catch (err) {
    if (!(err instanceof HttpError && err.status === 404)) {
      console.warn('manifest fetch failed', err);
    }
  }
}

// Runs up to PARALLEL_PULLS downloads concurrently; each file_ready event or
// finished download re-enters the loop to top the pool back up.
function pump() {
  if (!current || current.pumping) return;
  current.pumping = true;
  (async () => {
    try {
      while (current) {
        const rows = await jobRepo.pendingImportTracks(current.jobId);
        const available = rows.filter((r) => !current.inFlight.has(r.n));

        while (current && current.inFlight.size < PARALLEL_PULLS && available.length) {
          const row = available.shift();
          let entry = current.manifest?.tracks?.find((t) => t.n === row.n);
          if (!entry) {
            await ensureManifest(row.n + 1);
            entry = current.manifest?.tracks?.find((t) => t.n === row.n);
          }
          if (!entry) {
            // Manifest gone (job expired/cancelled) — nothing to pull for it.
            await jobRepo.setImportTrackState(current.jobId, row.n, 'failed');
            continue;
          }
          const jobRef = current;
          const promise = downloadOne(entry, row)
            .catch((err) => console.warn('import pull crashed', err))
            .finally(() => {
              jobRef.inFlight.delete(row.n);
            });
          current.inFlight.set(row.n, promise);
        }

        if (!current) return;
        if (current.inFlight.size === 0) {
          if (current.terminalStatus) {
            await finalize();
          }
          return;
        }
        // Wait for one slot to free up, then re-evaluate.
        await Promise.race([...current.inFlight.values()]);
      }
    } catch (err) {
      console.warn('import pump crashed', err);
    } finally {
      if (current) current.pumping = false;
    }
  })();
}

// Update one download's slot in the active-pulls map (null clears it).
function patchPull(n, fields) {
  const pulls = { ...useImportStore.getState().pulls };
  if (fields === null) delete pulls[n];
  else pulls[n] = { ...(pulls[n] || {}), ...fields };
  patchImport({ pulls });
}

async function downloadOne(entry, row) {
  // Capture identifiers up front: the download outlives many awaits and
  // `current` must not be dereferenced after they resolve.
  const { jobId, sourceUrl } = current;
  await jobRepo.setImportTrackState(jobId, entry.n, 'downloading');
  for (let attempt = row.attempts; attempt < MAX_ATTEMPTS; attempt += 1) {
    const trackId = randomId();
    const part = partFile(trackId);
    try {
      patchPull(entry.n, { title: entry.title, bytesWritten: 0, totalBytes: entry.fileSize || -1 });
      const task = File.createDownloadTask(jobsApi.fileUrl(jobId, entry.n), part, {
        headers: authHeaders(),
        onProgress: ({ bytesWritten, totalBytes }) => {
          patchPull(entry.n, { title: entry.title, bytesWritten, totalBytes });
        },
      });
      await task.downloadAsync();
      if (entry.fileSize > 0 && part.size !== entry.fileSize) {
        throw new Error(`Size mismatch (${part.size} vs ${entry.fileSize})`);
      }

      let artPath = null;
      if (entry.hasArt) {
        try {
          const art = artFile(trackId);
          await File.downloadFileAsync(jobsApi.artUrl(jobId, entry.n), art, {
            headers: authHeaders(),
            idempotent: true,
          });
          artPath = `art/${trackId}.jpg`;
        } catch {
          // Cover art is optional; keep the track without it.
        }
      }

      const dest = trackFile(trackId);
      if (dest.exists) dest.delete();
      part.moveSync(dest);

      await insertTrack({
        id: trackId,
        title: entry.title,
        artist: entry.artist,
        album: entry.album,
        albumArtist: entry.albumArtist || entry.artist,
        trackNumber: entry.trackNumber,
        durationMs: entry.durationMs,
        isrc: entry.isrc,
        quality: entry.quality,
        mime: entry.mime || 'audio/flac',
        fileSize: entry.fileSize > 0 ? entry.fileSize : dest.size,
        filePath: `music/${trackId}.flac`,
        artPath,
        lyrics: entry.lyrics,
        sourceUrl,
      });
      await jobRepo.setImportTrackState(jobId, entry.n, 'done', trackId);
      patchPull(entry.n, null);
      const counts = await jobRepo.importTrackCounts(jobId);
      patchImport({ saved: counts?.done ?? 0, failed: counts?.failed ?? 0 });
      bumpLibrary();
      return;
    } catch (err) {
      try {
        if (part.exists) part.delete();
      } catch {
        // Ignore.
      }
      await jobRepo.bumpImportTrackAttempts(jobId, entry.n);
      const gone = err instanceof HttpError && [404, 410].includes(err.status);
      if (attempt + 1 >= MAX_ATTEMPTS || gone || !current) break;
      await sleep(RETRY_DELAY_MS[Math.min(attempt, RETRY_DELAY_MS.length - 1)]);
    }
  }
  await jobRepo.setImportTrackState(jobId, entry.n, 'failed');
  patchPull(entry.n, null);
  const counts = await jobRepo.importTrackCounts(jobId);
  patchImport({ saved: counts?.done ?? 0, failed: counts?.failed ?? 0 });
}

async function finalize() {
  if (!current) return;
  const { jobId, terminalStatus, backendError } = current;
  const counts = await jobRepo.importTrackCounts(jobId);
  const saved = counts?.done ?? 0;
  const failedPulls = counts?.failed ?? 0;
  const success = terminalStatus === 'completed' && failedPulls === 0;

  current.socket?.close();

  patchImport({ phase: 'cleanup' });
  try {
    // Tell the backend we're done so it can drop its temp files. Non-fatal
    // on failure — the server reaper cleans up on its own schedule.
    await jobsApi.deleteJob(jobId);
  } catch {
    // Ignore.
  }

  if (success) {
    await jobRepo.updateJob(jobId, { status: 'done' });
    patchImport({ phase: 'done', saved, failed: 0, pulls: {}, currentLabel: null });
  } else {
    let error = backendError;
    if (!error) {
      if (terminalStatus === 'cancelled') error = 'Import cancelled';
      else if (failedPulls > 0) error = `${failedPulls} track(s) could not be downloaded`;
      else error = 'Import failed';
    }
    await jobRepo.updateJob(jobId, { status: 'failed', error });
    patchImport({ phase: 'failed', error, saved, failed: failedPulls, pulls: {}, currentLabel: null });
  }
  current = null;
  if (saved > 0) bumpLibrary();
}

export async function cancelImport() {
  if (!current) return;
  try {
    await jobsApi.cancelJob(current.jobId);
  } catch {
    // If the cancel request fails the WS terminal event may never come;
    // treat it as locally failed so the UI is never stuck.
    if (current) {
      current.terminalStatus = 'cancelled';
      pump();
    }
  }
}

// Called once at app boot: recover jobs that were mid-flight when the app
// last closed. Already-saved tracks always survive; the job itself usually
// cannot (the backend auto-cancels ~20s after our socket drops).
export async function resumePendingJobs() {
  ensureDirs();
  sweepPartFiles();
  const rows = await jobRepo.nonTerminalJobs();
  for (const row of rows) {
    if (current) {
      // Only one job can drain at a time; anything else is stale.
      await jobRepo.updateJob(row.id, { status: 'failed', error: 'Interrupted' });
      continue;
    }
    let backendJob = null;
    try {
      backendJob = await jobsApi.getJob(row.id);
    } catch (err) {
      await jobRepo.updateJob(row.id, {
        status: 'failed',
        error: err instanceof HttpError && err.status === 404 ? 'Job expired on server' : err.message,
      });
      continue;
    }
    attach(row.id, row.source_url);
    if (['completed', 'failed', 'cancelled'].includes(backendJob.status)) {
      current.terminalStatus = backendJob.status;
      current.backendError = backendJob.error || null;
      patchImport({ phase: 'draining', backendStatus: backendJob.status, total: backendJob.total || 0 });
      await ensureManifest(Infinity);
      pump();
    }
    // If still running/queued the socket we just opened resumes the flow.
  }
}
