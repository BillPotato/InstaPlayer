import { serverConfig } from './client';

// The backend auto-cancels a running job if no WebSocket subscriber is
// attached for more than ~20 seconds, so reconnects must be fast and eager.
const BACKOFF_MS = [1000, 2000, 4000];

export class JobEventSocket {
  constructor(jobId, { onEvent, onConnected, onDisconnected } = {}) {
    this.jobId = jobId;
    this.onEvent = onEvent;
    this.onConnected = onConnected;
    this.onDisconnected = onDisconnected;
    this.ws = null;
    this.closed = false;
    this.terminal = false;
    this.attempt = 0;
    this.reconnectTimer = null;
  }

  open() {
    if (this.closed || this.terminal) return;
    const { baseUrl, apiKey } = serverConfig();
    const wsBase = baseUrl.replace(/^http/i, 'ws');
    const url = `${wsBase}/jobs/${this.jobId}/events?token=${encodeURIComponent(apiKey)}`;
    const ws = new WebSocket(url);
    this.ws = ws;

    ws.onopen = () => {
      if (ws !== this.ws) return;
      this.attempt = 0;
      this.onConnected?.();
    };
    ws.onmessage = (msg) => {
      if (ws !== this.ws) return;
      let event;
      try {
        event = JSON.parse(msg.data);
      } catch {
        return;
      }
      if (event?.type === 'status' && ['completed', 'failed', 'cancelled'].includes(event.status)) {
        this.terminal = true;
      }
      this.onEvent?.(event);
    };
    ws.onclose = () => {
      if (ws !== this.ws) return;
      this.ws = null;
      this.onDisconnected?.();
      this.scheduleReconnect();
    };
    ws.onerror = () => {
      // onclose follows; nothing to do here.
    };
  }

  scheduleReconnect() {
    if (this.closed || this.terminal || this.reconnectTimer) return;
    const delay = BACKOFF_MS[Math.min(this.attempt, BACKOFF_MS.length - 1)];
    this.attempt += 1;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.open();
    }, delay);
  }

  // Reconnect immediately (used when the app returns to the foreground).
  kick() {
    if (this.closed || this.terminal || this.ws) return;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.open();
  }

  close() {
    this.closed = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    const ws = this.ws;
    this.ws = null;
    try {
      ws?.close();
    } catch {
      // Already closed.
    }
  }
}
