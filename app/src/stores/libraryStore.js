import { create } from 'zustand';

// Cheap cross-screen invalidation: screens re-query their repos when tick changes.
export const useLibraryStore = create((set) => ({
  tick: 0,
  bump: () => set((s) => ({ tick: s.tick + 1 })),
}));

export function bumpLibrary() {
  useLibraryStore.getState().bump();
}
