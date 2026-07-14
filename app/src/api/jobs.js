import { apiFetch, serverConfig } from './client';

export function createJob(sourceUrl, preferredSource, quality) {
  const body = { spotifyUrl: sourceUrl };
  if (preferredSource) body.preferredSource = preferredSource;
  if (quality) body.quality = quality;
  return apiFetch('/jobs', { method: 'POST', body, timeoutMs: 30000 });
}

export function getJob(jobId) {
  return apiFetch(`/jobs/${jobId}`);
}

export function cancelJob(jobId) {
  return apiFetch(`/jobs/${jobId}/cancel`, { method: 'POST' });
}

export function deleteJob(jobId) {
  return apiFetch(`/jobs/${jobId}`, { method: 'DELETE' });
}

export function getManifest(jobId) {
  return apiFetch(`/jobs/${jobId}/manifest`);
}

export function fileUrl(jobId, n) {
  return `${serverConfig().baseUrl}/jobs/${jobId}/files/${n}`;
}

export function artUrl(jobId, n) {
  return `${serverConfig().baseUrl}/jobs/${jobId}/art/${n}`;
}

// The single source of truth for whether the backend is working: reachability
// (the request succeeds), auth (401/403 on a bad key), and engine availability
// (the `importable` field) all surface here. The frontend has no separate
// connection/probe test — it only knows the backend's health through this.
export function getDownloaderStatus() {
  return apiFetch('/downloader/status');
}
