import { File } from 'expo-file-system';
import { pickAudioFiles, pickAudioFolder } from './pickers';
import { parseMetadata, fallbackMeta, extOf, mimeForExt } from './metadata';
import { musicDir, artFile, ensureDirs } from '../downloads/paths';
import { insertTrack, findDuplicate } from '../db/trackRepo';
import { randomId } from '../utils/uuid';
import { bumpLibrary } from '../stores/libraryStore';
import { useLocalImportStore, patchLocalImport } from '../stores/localImportStore';

let running = false;

export async function pickAndImportFiles() {
  const files = await pickAudioFiles();
  if (files.length) await importFiles(files);
  return files.length;
}

export async function pickAndImportFolder() {
  const files = await pickAudioFolder();
  if (files.length) await importFiles(files);
  return files.length;
}

// Sequential import: copy into app storage → parse tags from the local copy
// (SAF sources are read-only and seek-limited) → save art → insert DB row.
export async function importFiles(pickedFiles) {
  if (running) throw new Error('An import is already running');
  running = true;
  ensureDirs();
  useLocalImportStore.getState().reset();
  patchLocalImport({ phase: 'running', total: pickedFiles.length });

  let done = 0;
  let failed = 0;
  let skipped = 0;
  const errors = [];

  try {
    for (const picked of pickedFiles) {
      const name = picked.name || 'unknown';
      patchLocalImport({ currentName: name });
      const id = randomId();
      const ext = extOf(name) || 'mp3';
      const dest = new File(musicDir, `${id}.${ext}`);
      try {
        await picked.copy(dest);

        let meta;
        try {
          meta = parseMetadata(dest);
        } catch {
          meta = fallbackMeta(name);
        }

        const dup = await findDuplicate(meta.title, meta.artist, dest.size);
        if (dup) {
          dest.delete();
          skipped += 1;
          patchLocalImport({ skipped });
          continue;
        }

        let artPath = null;
        if (meta.artBytes?.length) {
          try {
            const art = artFile(id);
            art.write(meta.artBytes);
            artPath = `art/${id}.jpg`;
          } catch {
            // Art is optional.
          }
        }

        await insertTrack({
          id,
          title: meta.title,
          artist: meta.artist,
          album: meta.album,
          albumArtist: meta.albumArtist || meta.artist,
          trackNumber: meta.trackNumber,
          durationMs: meta.durationMs,
          isrc: null,
          quality: null,
          mime: mimeForExt(ext),
          fileSize: dest.size,
          filePath: `music/${id}.${ext}`,
          artPath,
          lyrics: meta.lyrics,
          sourceUrl: null,
        });
        done += 1;
        patchLocalImport({ done });
        if (done % 5 === 0) bumpLibrary();
      } catch (err) {
        try {
          if (dest.exists) dest.delete();
        } catch {
          // Ignore.
        }
        failed += 1;
        if (errors.length < 10) errors.push({ name, message: String(err?.message || err) });
        patchLocalImport({ failed, errors: [...errors] });
      }
    }
  } finally {
    running = false;
    patchLocalImport({ phase: 'done', currentName: null, done, failed, skipped, errors });
    if (done > 0) bumpLibrary();
  }
  return { done, failed, skipped };
}
