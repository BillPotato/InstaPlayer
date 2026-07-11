import { deleteTrackRow } from '../db/trackRepo';
import { deleteTrackFiles } from '../downloads/paths';
import { handleTrackDeleted } from '../player/playerService';
import { bumpLibrary } from '../stores/libraryStore';

// Remove a downloaded track completely: live queue, audio + art files, DB row
// (cascades clean playlist entries and history).
export async function deleteTrack(track) {
  handleTrackDeleted(track.id);
  deleteTrackFiles(track);
  await deleteTrackRow(track.id);
  bumpLibrary();
}
