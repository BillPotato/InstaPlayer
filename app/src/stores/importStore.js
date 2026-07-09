import { create } from 'zustand';

const idle = {
  jobId: null,
  name: null,
  sourceUrl: null,
  phase: 'idle', // idle | creating | active | draining | cleanup | done | failed
  backendStatus: null,
  total: 0,
  backendCompleted: 0,
  saved: 0,
  failed: 0,
  currentLabel: null,
  pulls: {}, // active device pulls, keyed by n: { title, bytesWritten, totalBytes }
  error: null,
  connected: false,
};

export const useImportStore = create((set) => ({
  ...idle,
  patch: (fields) => set(fields),
  reset: () => set({ ...idle }),
}));

export function patchImport(fields) {
  useImportStore.getState().patch(fields);
}
