import { useSettingsStore } from '../stores/settingsStore';

export class HttpError extends Error {
  constructor(status, detail) {
    super(detail || `HTTP ${status}`);
    this.name = 'HttpError';
    this.status = status;
    this.detail = detail;
  }
}

export function serverConfig() {
  const { serverUrl, apiKey } = useSettingsStore.getState();
  if (!serverUrl) throw new Error('No server configured');
  return { baseUrl: serverUrl, apiKey };
}

export function authHeaders() {
  const { apiKey } = serverConfig();
  return { Authorization: `Bearer ${apiKey}` };
}

async function parseDetail(res) {
  try {
    const data = await res.json();
    if (data && typeof data.detail === 'string') return data.detail;
  } catch {
    // Non-JSON error body; fall through to status text.
  }
  return null;
}

export async function apiFetch(path, { method = 'GET', body, timeoutMs = 15000, baseUrl, apiKey } = {}) {
  const cfg = baseUrl != null ? { baseUrl, apiKey } : serverConfig();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let res;
  try {
    res = await fetch(`${cfg.baseUrl}${path}`, {
      method,
      headers: {
        ...(cfg.apiKey ? { Authorization: `Bearer ${cfg.apiKey}` } : {}),
        ...(body != null ? { 'Content-Type': 'application/json' } : {}),
      },
      body: body != null ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });
  } catch (err) {
    if (err?.name === 'AbortError') throw new Error('Request timed out');
    throw new Error(`Could not reach server (${err?.message || 'network error'})`);
  } finally {
    clearTimeout(timer);
  }
  if (!res.ok) {
    throw new HttpError(res.status, await parseDetail(res));
  }
  if (res.status === 204) return null;
  return res.json();
}
