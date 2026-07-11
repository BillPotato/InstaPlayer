import { createAudioPlayer, setAudioModeAsync } from 'expo-audio';
import { Platform, PermissionsAndroid } from 'react-native';
import { usePlayerStore, currentTrackOf } from './playerStore';
import { audioUriForTrack, artUriForTrack } from '../downloads/paths';
import { logPlay } from '../db/historyRepo';
import { setDurationMs, tracksByIds } from '../db/trackRepo';
import { getSetting, setSetting } from '../db/settingsRepo';

const PERSIST_KEY = 'player_state_v1';
const FADE_MS = 250;
const SLEEP_FADE_MS = 3000;

// Playback engine: one expo-audio AudioPlayer + a JS-managed queue.
//
// expo-audio's AudioPlaylist would give native gapless playback, but as of
// expo-audio 56.x only a plain AudioPlayer can drive the lock-screen /
// notification media session (the playlist integration is merged upstream
// but unreleased — expo/expo#46020). When it ships, swap the internals here
// for an AudioPlaylist; the public functions can stay as they are.

let player = null;
let advancing = false;
let historyLogged = false;
let durationSaved = false;
let askedNotifPermission = false;
let sleepTimerHandle = null;
let fadeHandle = null;
let persistHandle = null;
let statusTicks = 0;

const store = () => usePlayerStore.getState();
const patch = (fields) => usePlayerStore.getState().patch(fields);

// ---------------------------------------------------------------------------
// Volume fades (expo-audio has no native fade; ramp the volume property)
// ---------------------------------------------------------------------------

function cancelFade() {
  if (fadeHandle) {
    clearInterval(fadeHandle);
    fadeHandle = null;
  }
}

function fadeTo(target, ms, done) {
  if (!player) {
    done?.();
    return;
  }
  cancelFade();
  const start = player.volume;
  const steps = Math.max(1, Math.round(ms / 50));
  let i = 0;
  fadeHandle = setInterval(() => {
    i += 1;
    player.volume = Math.max(0, Math.min(1, start + ((target - start) * i) / steps));
    if (i >= steps) {
      cancelFade();
      done?.();
    }
  }, 50);
}

// ---------------------------------------------------------------------------
// Persistence: queue + position survive app restarts (restored paused)
// ---------------------------------------------------------------------------

function schedulePersist() {
  if (persistHandle) clearTimeout(persistHandle);
  persistHandle = setTimeout(() => {
    persistHandle = null;
    const s = store();
    const payload =
      s.pos >= 0
        ? JSON.stringify({
            ids: s.queue.map((t) => t.id),
            order: s.order,
            pos: s.pos,
            shuffle: s.shuffle,
            repeat: s.repeat,
            currentTime: Math.floor(s.currentTime),
          })
        : '';
    setSetting(PERSIST_KEY, payload).catch(() => {});
  }, 800);
}

async function restorePersistedState() {
  const raw = await getSetting(PERSIST_KEY, '');
  if (!raw) return;
  let saved;
  try {
    saved = JSON.parse(raw);
  } catch {
    return;
  }
  const ids = Array.isArray(saved?.ids) ? saved.ids : null;
  const order = Array.isArray(saved?.order) ? saved.order : null;
  // order must be a valid permutation of [0, ids.length); reject anything
  // malformed so corruption can never crash boot or misalign the queue.
  if (!ids || !order || order.length !== ids.length) return;
  if (!order.every((i) => Number.isInteger(i) && i >= 0 && i < ids.length)) return;
  const tracks = await tracksByIds(ids);
  // Deleted tracks would shift every order index; only restore intact queues.
  if (tracks.length !== ids.length) return;
  patch({
    queue: tracks,
    order,
    pos: Math.min(Math.max(0, Number(saved.pos) || 0), order.length - 1),
    shuffle: !!saved.shuffle,
    repeat: ['off', 'all', 'one'].includes(saved.repeat) ? saved.repeat : 'off',
  });
  loadCurrent(false);
  const resumeAt = Number(saved.currentTime);
  if (resumeAt > 0) {
    seekTo(resumeAt);
    patch({ currentTime: resumeAt });
  }
}

export async function initPlayer() {
  if (player) return;
  await setAudioModeAsync({
    playsInSilentMode: true,
    shouldPlayInBackground: true,
    interruptionMode: 'doNotMix',
  });
  player = createAudioPlayer(null, { updateInterval: 250 });
  player.addListener('playbackStatusUpdate', onStatus);
  const savedRate = parseFloat(await getSetting('playback_rate', '1'));
  if (Number.isFinite(savedRate) && savedRate > 0) patch({ rate: savedRate });
  // Persist queue shape changes; position is folded in on pause/track ticks.
  usePlayerStore.subscribe((s, prev) => {
    if (
      s.queue !== prev.queue || s.order !== prev.order || s.pos !== prev.pos ||
      s.shuffle !== prev.shuffle || s.repeat !== prev.repeat
    ) {
      schedulePersist();
    }
  });
  await restorePersistedState().catch(() => {});
}

function onStatus(status) {
  const s = store();
  patch({
    currentTime: status.currentTime || 0,
    duration: status.duration || s.duration,
    isPlaying: status.playing,
    isBuffering: status.isBuffering,
  });
  const track = currentTrackOf(s);
  if (track && !historyLogged && status.currentTime >= Math.min(30, (status.duration || 60) / 2)) {
    historyLogged = true;
    logPlay(track.id).catch(() => {});
  }
  // Locally imported files may arrive without a parsed duration; save the
  // real one the first time the track actually loads.
  if (track && !durationSaved && !track.duration_ms && status.isLoaded && status.duration > 0) {
    durationSaved = true;
    const ms = Math.round(status.duration * 1000);
    track.duration_ms = ms;
    setDurationMs(track.id, ms).catch(() => {});
  }
  if (status.didJustFinish && !advancing) {
    advancing = true;
    try {
      handleTrackEnd();
    } finally {
      advancing = false;
    }
  }
  // Fold the playhead into the persisted state every ~10s while playing.
  statusTicks += 1;
  if (status.playing && statusTicks % 40 === 0) schedulePersist();
}

function metadataFor(track) {
  const artUri = artUriForTrack(track);
  return {
    title: track.title,
    artist: track.artist,
    albumTitle: track.album,
    ...(artUri ? { artworkUrl: artUri } : {}),
  };
}

function loadCurrent(autoplay) {
  const s = store();
  const track = currentTrackOf(s);
  if (!track || !player) return;
  historyLogged = false;
  durationSaved = false;
  cancelFade();
  player.volume = 1;
  player.replace({ uri: audioUriForTrack(track) });
  player.setPlaybackRate(s.rate, 'high');
  player.setActiveForLockScreen(true, metadataFor(track), {
    showSeekForward: false,
    showSeekBackward: false,
  });
  patch({ currentTime: 0, duration: (track.duration_ms || 0) / 1000 });
  if (autoplay) player.play();
}

async function requestNotifPermission() {
  if (askedNotifPermission || Platform.OS !== 'android' || Platform.Version < 33) return;
  askedNotifPermission = true;
  try {
    await PermissionsAndroid.request(PermissionsAndroid.PERMISSIONS.POST_NOTIFICATIONS);
  } catch {
    // Playback works without the notification permission; controls just stay hidden.
  }
}

function buildOrder(length, shuffle, startIndex) {
  const identity = Array.from({ length }, (_, i) => i);
  if (!shuffle) return { order: identity, pos: startIndex };
  const rest = identity.filter((i) => i !== startIndex);
  for (let i = rest.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [rest[i], rest[j]] = [rest[j], rest[i]];
  }
  return { order: [startIndex, ...rest], pos: 0 };
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export function playContext(tracks, startIndex = 0, { shuffle } = {}) {
  if (!tracks?.length) return;
  requestNotifPermission();
  const useShuffle = shuffle ?? store().shuffle;
  const { order, pos } = buildOrder(tracks.length, useShuffle, Math.max(0, startIndex));
  patch({ queue: [...tracks], order, pos, shuffle: useShuffle });
  loadCurrent(true);
}

export function shufflePlay(tracks) {
  if (!tracks?.length) return;
  playContext(tracks, Math.floor(Math.random() * tracks.length), { shuffle: true });
}

export function togglePlay() {
  const s = store();
  if (s.pos < 0 || !player) return;
  if (s.isPlaying) {
    pause();
  } else {
    cancelFade();
    player.volume = 0;
    player.play();
    fadeTo(1, FADE_MS);
  }
}

// Fading pause (user-facing). hardPause is for cases where the audio has
// already ended or must stop immediately.
export function pause() {
  if (!player) return;
  fadeTo(0, FADE_MS, () => {
    player.pause();
    player.volume = 1;
    schedulePersist();
  });
}

function hardPause() {
  if (!player) return;
  cancelFade();
  player.pause();
  player.volume = 1;
  schedulePersist();
}

export function seekTo(seconds) {
  player?.seekTo(Math.max(0, seconds));
}

export function next() {
  advanceTo(store().pos + 1, { wrap: true, autoplay: true });
}

export function previous() {
  const s = store();
  if (s.pos < 0) return;
  if (s.currentTime > 3) {
    seekTo(0);
    return;
  }
  if (s.pos > 0) {
    advanceTo(s.pos - 1, { autoplay: true });
  } else if (s.repeat === 'all' && s.order.length > 0) {
    advanceTo(s.order.length - 1, { autoplay: true });
  } else {
    seekTo(0);
  }
}

function advanceTo(newPos, { wrap = false, autoplay = true } = {}) {
  const s = store();
  if (!s.order.length) return;
  let pos = newPos;
  if (pos >= s.order.length) {
    if (s.repeat === 'all' || wrap) pos = 0;
    else return;
  }
  if (pos < 0) pos = 0;
  patch({ pos });
  loadCurrent(autoplay);
}

function handleTrackEnd() {
  const s = store();
  if (s.sleepEndOfTrack) {
    clearSleepTimer();
    hardPause();
    return;
  }
  if (s.repeat === 'one') {
    seekTo(0);
    player.play();
    return;
  }
  if (s.pos + 1 >= s.order.length && s.repeat !== 'all') {
    // End of queue: stay on the last track, paused at the start.
    seekTo(0);
    hardPause();
    return;
  }
  advanceTo(s.pos + 1, { autoplay: true });
}

export function toggleShuffle() {
  const s = store();
  if (s.pos < 0) {
    patch({ shuffle: !s.shuffle });
    return;
  }
  const currentQueueIndex = s.order[s.pos];
  if (!s.shuffle) {
    const rest = s.order.filter((i) => i !== currentQueueIndex);
    for (let i = rest.length - 1; i > 0; i -= 1) {
      const j = Math.floor(Math.random() * (i + 1));
      [rest[i], rest[j]] = [rest[j], rest[i]];
    }
    patch({ shuffle: true, order: [currentQueueIndex, ...rest], pos: 0 });
  } else {
    const identity = Array.from({ length: s.queue.length }, (_, i) => i);
    patch({ shuffle: false, order: identity, pos: currentQueueIndex });
  }
}

export function cycleRepeat() {
  const seq = { off: 'all', all: 'one', one: 'off' };
  patch({ repeat: seq[store().repeat] });
}

export function setRate(rate) {
  const clamped = Math.min(2, Math.max(0.5, rate));
  player?.setPlaybackRate(clamped, 'high');
  patch({ rate: clamped });
  setSetting('playback_rate', String(clamped)).catch(() => {});
}

export function enqueueNext(track) {
  const s = store();
  if (s.pos < 0) {
    playContext([track], 0);
    return;
  }
  const queue = [...s.queue, track];
  const order = [...s.order];
  order.splice(s.pos + 1, 0, queue.length - 1);
  patch({ queue, order });
}

export function enqueueLast(tracks) {
  const list = Array.isArray(tracks) ? tracks : [tracks];
  const s = store();
  if (s.pos < 0) {
    playContext(list, 0);
    return;
  }
  const queue = [...s.queue];
  const order = [...s.order];
  for (const t of list) {
    queue.push(t);
    order.push(queue.length - 1);
  }
  patch({ queue, order });
}

export function jumpTo(orderIndex) {
  const s = store();
  if (orderIndex < 0 || orderIndex >= s.order.length) return;
  patch({ pos: orderIndex });
  loadCurrent(true);
}

export function removeFromQueue(orderIndex) {
  const s = store();
  if (orderIndex === s.pos || orderIndex < 0 || orderIndex >= s.order.length) return;
  const order = [...s.order];
  order.splice(orderIndex, 1);
  patch({ order, pos: orderIndex < s.pos ? s.pos - 1 : s.pos });
}

export function moveInQueue(fromOrderIndex, toOrderIndex) {
  const s = store();
  if (
    fromOrderIndex === s.pos ||
    fromOrderIndex < 0 || fromOrderIndex >= s.order.length ||
    toOrderIndex < 0 || toOrderIndex >= s.order.length
  ) {
    return;
  }
  const order = [...s.order];
  const [moved] = order.splice(fromOrderIndex, 1);
  order.splice(toOrderIndex, 0, moved);
  let pos = s.pos;
  if (fromOrderIndex < pos && toOrderIndex >= pos) pos -= 1;
  else if (fromOrderIndex > pos && toOrderIndex <= pos) pos += 1;
  patch({ order, pos });
}

// Drop a deleted track from the live queue; if it is playing, move on.
export function handleTrackDeleted(trackId) {
  const s = store();
  if (!s.queue.some((t) => t.id === trackId)) return;
  const wasPlaying = s.isPlaying;
  const current = currentTrackOf(s);
  const ordered = s.order.map((i) => s.queue[i]);
  const kept = [];
  let removedBeforePos = 0;
  ordered.forEach((t, idx) => {
    if (t && t.id !== trackId) kept.push(t);
    else if (idx < s.pos) removedBeforePos += 1;
  });
  if (!kept.length) {
    stopAndClear();
    return;
  }
  let pos;
  if (current && current.id !== trackId) {
    pos = kept.indexOf(current);
    if (pos < 0) pos = Math.min(Math.max(0, s.pos - removedBeforePos), kept.length - 1);
  } else {
    // Current track was deleted: land on whatever followed it.
    pos = Math.min(Math.max(0, s.pos - removedBeforePos), kept.length - 1);
  }
  patch({
    queue: kept,
    order: kept.map((_, i) => i),
    pos,
  });
  if (!current || current.id === trackId) {
    loadCurrent(wasPlaying);
  }
}

export function stopAndClear() {
  cancelFade();
  if (player) player.volume = 1;
  player?.pause();
  try {
    player?.clearLockScreenControls();
  } catch {
    // Not active — fine.
  }
  clearSleepTimer();
  patch({ queue: [], order: [], pos: -1, isPlaying: false, currentTime: 0, duration: 0 });
}

// ---------------------------------------------------------------------------
// Sleep timer
// ---------------------------------------------------------------------------

export function setSleepTimer(minutes) {
  clearSleepTimer();
  if (minutes === 'end') {
    patch({ sleepEndOfTrack: true, sleepAt: null });
    return;
  }
  const ms = minutes * 60 * 1000;
  patch({ sleepAt: Date.now() + ms, sleepEndOfTrack: false });
  sleepTimerHandle = setTimeout(() => {
    sleepTimerHandle = null;
    patch({ sleepAt: null, sleepEndOfTrack: false });
    // Gentle fade-out rather than an abrupt stop mid-song.
    fadeTo(0, SLEEP_FADE_MS, () => {
      player?.pause();
      if (player) player.volume = 1;
      schedulePersist();
    });
  }, ms);
}

export function clearSleepTimer() {
  if (sleepTimerHandle) {
    clearTimeout(sleepTimerHandle);
    sleepTimerHandle = null;
  }
  patch({ sleepAt: null, sleepEndOfTrack: false });
}
