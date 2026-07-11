import { Directory, File } from 'expo-file-system';

export const AUDIO_EXT = /\.(flac|mp3|m4a|aac|ogg|opus|wav)$/i;

const MAX_DEPTH = 10;
const MAX_FILES = 2000;

function isAudioFile(entry) {
  try {
    if (AUDIO_EXT.test(entry.name || '')) return true;
    // SAF display names don't always carry an extension; trust the mime too.
    return typeof entry.type === 'string' && entry.type.startsWith('audio/');
  } catch {
    return false;
  }
}

// System multi-file picker. Returns [] when the user cancels.
export async function pickAudioFiles() {
  const res = await File.pickFileAsync({ multipleFiles: true, mimeTypes: ['audio/*'] });
  if (res.canceled || !res.result) return [];
  return res.result.filter(isAudioFile);
}

// System folder picker + recursive walk. Returns [] when cancelled.
export async function pickAudioFolder() {
  let dir;
  try {
    dir = await Directory.pickDirectoryAsync();
  } catch {
    return [];
  }
  if (!dir) return [];
  const found = [];
  walk(dir, 0, found);
  return found;
}

function walk(dir, depth, found) {
  if (depth > MAX_DEPTH || found.length >= MAX_FILES) return;
  let entries;
  try {
    entries = dir.list();
  } catch {
    return;
  }
  for (const entry of entries) {
    if (found.length >= MAX_FILES) return;
    if (entry instanceof Directory) {
      walk(entry, depth + 1, found);
    } else if (isAudioFile(entry)) {
      found.push(entry);
    }
  }
}
