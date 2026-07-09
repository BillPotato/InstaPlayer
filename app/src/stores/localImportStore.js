import { create } from 'zustand';

const idle = {
  phase: 'idle', // idle | running | done
  total: 0,
  done: 0,
  failed: 0,
  skipped: 0,
  currentName: null,
  errors: [], // [{ name, message }] capped
};

export const useLocalImportStore = create((set) => ({
  ...idle,
  patch: (fields) => set(fields),
  reset: () => set({ ...idle }),
}));

export function patchLocalImport(fields) {
  useLocalImportStore.getState().patch(fields);
}
