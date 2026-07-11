import { useState } from 'react';
import { Alert } from 'react-native';
import { useRouter } from 'expo-router';
import { SheetMenu } from './SheetMenu';
import { PlaylistPickerSheet } from './PlaylistPickerSheet';
import { enqueueNext, enqueueLast } from '../player/playerService';
import { deleteTrack } from '../library/libraryActions';
import { formatBytes } from '../utils/format';

// Shared long-press menu for a track. Usage:
//   const menu = useTrackMenu();
//   ... onLongPress={() => menu.open(track)} ...
//   {menu.element}
export function useTrackMenu({ extraItems } = {}) {
  const router = useRouter();
  const [track, setTrack] = useState(null);
  const [pickerTrack, setPickerTrack] = useState(null);

  const open = (t) => setTrack(t);

  const confirmDelete = (t) => {
    Alert.alert(
      'Delete download?',
      `"${t.title}" (${formatBytes(t.file_size)}) will be removed from this device, including from your playlists.`,
      [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Delete', style: 'destructive', onPress: () => deleteTrack(t) },
      ]
    );
  };

  const albumKey = (t) => encodeURIComponent(`${t.album_artist}:::${t.album}`);

  const element = (
    <>
      <SheetMenu
        visible={!!track}
        onClose={() => setTrack(null)}
        title={track?.title}
        subtitle={track ? `${track.artist} — ${track.album}` : null}
        items={
          track
            ? [
                { key: 'next', label: 'Play next', icon: 'play-skip-forward-outline', onPress: () => enqueueNext(track) },
                { key: 'queue', label: 'Add to queue', icon: 'list-outline', onPress: () => enqueueLast(track) },
                { key: 'playlist', label: 'Add to playlist', icon: 'add-circle-outline', onPress: () => setPickerTrack(track) },
                { key: 'album', label: 'Go to album', icon: 'disc-outline', onPress: () => router.push(`/library/album/${albumKey(track)}`) },
                { key: 'artist', label: 'Go to artist', icon: 'person-outline', onPress: () => router.push(`/library/artist/${encodeURIComponent(track.artist)}`) },
                ...(extraItems ? extraItems(track) : []),
                { key: 'delete', label: 'Delete download', icon: 'trash-outline', destructive: true, onPress: () => confirmDelete(track) },
              ]
            : []
        }
      />
      <PlaylistPickerSheet
        visible={!!pickerTrack}
        trackIds={pickerTrack ? [pickerTrack.id] : []}
        onClose={() => setPickerTrack(null)}
      />
    </>
  );

  return { open, element };
}
