import { Directory, File, Paths } from 'expo-file-system';

export const musicDir = new Directory(Paths.document, 'music');
export const artDir = new Directory(Paths.document, 'art');

export function ensureDirs() {
  if (!musicDir.exists) musicDir.create({ intermediates: true });
  if (!artDir.exists) artDir.create({ intermediates: true });
}

export function trackFile(trackId) {
  return new File(musicDir, `${trackId}.flac`);
}

export function partFile(trackId) {
  return new File(musicDir, `${trackId}.part`);
}

export function artFile(trackId) {
  return new File(artDir, `${trackId}.jpg`);
}

export function fileForRelPath(relPath) {
  return new File(Paths.document, relPath);
}

export function artUriForTrack(track) {
  if (!track?.art_path) return null;
  return new File(Paths.document, track.art_path).uri;
}

export function audioUriForTrack(track) {
  return new File(Paths.document, track.file_path).uri;
}

export function deleteTrackFiles(track) {
  for (const rel of [track.file_path, track.art_path]) {
    if (!rel) continue;
    try {
      const f = new File(Paths.document, rel);
      if (f.exists) f.delete();
    } catch {
      // Best effort; orphaned files get cleaned by sweepOrphans.
    }
  }
}

// Delete leftover .part files from interrupted downloads.
export function sweepPartFiles() {
  try {
    if (!musicDir.exists) return;
    for (const entry of musicDir.list()) {
      if (entry instanceof File && entry.uri.endsWith('.part')) {
        try {
          entry.delete();
        } catch {
          // Ignore.
        }
      }
    }
  } catch {
    // Ignore.
  }
}
