import { create } from 'zustand';

// queue  — tracks in the order the user started them (context order)
// order  — play order as indices into queue (identity, or shuffled)
// pos    — index into order of the current track; -1 when nothing loaded
export const usePlayerStore = create((set) => ({
  queue: [],
  order: [],
  pos: -1,
  shuffle: false,
  repeat: 'off', // 'off' | 'all' | 'one'
  rate: 1,
  isPlaying: false,
  isBuffering: false,
  currentTime: 0,
  duration: 0,
  sleepAt: null, // epoch ms when playback will pause, or null
  sleepEndOfTrack: false,
  patch: (fields) => set(fields),
}));

export function currentTrackOf(state) {
  if (state.pos < 0 || state.pos >= state.order.length) return null;
  return state.queue[state.order[state.pos]] ?? null;
}

export function useCurrentTrack() {
  return usePlayerStore(currentTrackOf);
}

export function orderedQueueOf(state) {
  return state.order.map((i) => state.queue[i]).filter(Boolean);
}
