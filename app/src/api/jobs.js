import { apiFetch, serverConfig, HttpError } from './client';

export function createJob(sourceUrl, preferredSource) {
  const body = { spotifyUrl: sourceUrl };
  if (preferredSource) body.preferredSource = preferredSource;
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

// Availability of the server's download engine (SpotiFLAC). status is cheap;
// probe actually downloads one sample track server-side and can take minutes.
export function getDownloaderStatus() {
  return apiFetch('/downloader/status');
}

// force=true always runs a live download test; otherwise the backend answers
// instantly from its periodic-probe cache while fresh.
export function probeDownloader(force = false) {
  return apiFetch(`/downloader/probe${force ? '?force=true' : ''}`, {
    method: 'POST',
    timeoutMs: 300000,
  });
}

// Connection test used by the setup/server screens. Runs against explicit
// values (not yet saved). /health proves reachability; a GET for a job id
// that cannot exist proves the key: 404 = authorized, 401 = bad key.
export async function testConnection(baseUrl, apiKey) {
  await apiFetch('/health', { baseUrl, apiKey: '', timeoutMs: 8000 });
  try {
    await apiFetch(`/jobs/${'0'.repeat(32)}`, { baseUrl, apiKey, timeoutMs: 8000 });
    return true;
  } catch (err) {
    if (err instanceof HttpError && err.status === 404) return true;
    if (err instanceof HttpError && (err.status === 401 || err.status === 403)) {
      throw new Error('Server reachable, but the API key was rejected');
    }
    throw err;
  }
}
