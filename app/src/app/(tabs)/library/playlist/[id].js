import { useCallback, useState } from 'react';
import { Alert, Pressable, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useFocusEffect, useLocalSearchParams, useNavigation, useRouter } from 'expo-router';
import ReorderableList, { useReorderableDrag } from 'react-native-reorderable-list';
import { TrackArt } from '../../../../components/TrackArt';
import { TrackRow } from '../../../../components/TrackRow';
import { EmptyState } from '../../../../components/EmptyState';
import { SheetMenu } from '../../../../components/SheetMenu';
import { InputDialog } from '../../../../components/InputDialog';
import { useTrackMenu } from '../../../../components/TrackMenu';
import { PlayShuffleBar } from '../../../../components/PlayShuffleBar';
import { useTheme } from '../../../../theme/useTheme';
import { useLibraryStore, bumpLibrary } from '../../../../stores/libraryStore';
import {
  getPlaylist, playlistTracks, renamePlaylist, deletePlaylist,
  removePlaylistEntry, reorderPlaylist,
} from '../../../../db/playlistRepo';
import { playContext } from '../../../../player/playerService';
import { trackCountLabel } from '../../../../utils/format';

function DraggableRow({ item, index, tracks, colors, menu }) {
  const drag = useReorderableDrag();
  return (
    <TrackRow
      track={item}
      onPress={() => playContext(tracks, index)}
      onLongPress={drag}
      onMenuPress={() => menu.open(item)}
      right={
        <Pressable onLongPress={drag} delayLongPress={100} hitSlop={8} style={{ padding: 4, marginRight: 2 }}>
          <Ionicons name="reorder-three-outline" size={20} color={colors.textDim} />
        </Pressable>
      }
    />
  );
}

export default function PlaylistScreen() {
  const colors = useTheme();
  const navigation = useNavigation();
  const router = useRouter();
  const { id } = useLocalSearchParams();
  const tick = useLibraryStore((s) => s.tick);
  const [playlist, setPlaylist] = useState(null);
  const [tracks, setTracks] = useState([]);
  const [menuOpen, setMenuOpen] = useState(false);
  const [renameOpen, setRenameOpen] = useState(false);

  const menu = useTrackMenu({
    extraItems: (track) => [
      {
        key: 'remove',
        label: 'Remove from this playlist',
        icon: 'remove-circle-outline',
        onPress: async () => {
          await removePlaylistEntry(String(id), track.entry_id);
          bumpLibrary();
        },
      },
    ],
  });

  const reload = useCallback(() => {
    let alive = true;
    Promise.all([getPlaylist(String(id)), playlistTracks(String(id))]).then(([p, t]) => {
      if (!alive) return;
      setPlaylist(p);
      setTracks(t);
      navigation.setOptions({
        title: p?.name ?? '',
        headerRight: () => (
          <Pressable onPress={() => setMenuOpen(true)} hitSlop={8} style={{ padding: 4 }}>
            <Ionicons name="ellipsis-vertical" size={20} color={colors.text} />
          </Pressable>
        ),
      });
    });
    return () => {
      alive = false;
    };
  }, [id, navigation, colors.text]);

  useFocusEffect(
    useCallback(() => reload(), [reload, tick])
  );

  const onReorder = ({ from, to }) => {
    setTracks((prev) => {
      const next = [...prev];
      const [moved] = next.splice(from, 1);
      next.splice(to, 0, moved);
      return next;
    });
    reorderPlaylist(String(id), from, to).then(bumpLibrary);
  };

  const confirmDelete = () => {
    Alert.alert('Delete playlist?', `"${playlist?.name}" will be deleted. Songs stay in your library.`, [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Delete',
        style: 'destructive',
        onPress: async () => {
          await deletePlaylist(String(id));
          bumpLibrary();
          router.back();
        },
      },
    ]);
  };

  return (
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      {tracks.length === 0 ? (
        <EmptyState
          icon="musical-notes"
          title="This playlist is empty"
          message="Long-press any song and choose “Add to playlist”."
        />
      ) : (
        <ReorderableList
          data={tracks}
          keyExtractor={(t) => String(t.entry_id)}
          onReorder={onReorder}
          ListHeaderComponent={
            <View>
              <View style={{ alignItems: 'center', paddingTop: 16 }}>
                <TrackArt track={tracks.find((t) => t.art_path) || null} size={180} radius={10} />
                <Text style={{ color: colors.text, fontSize: 20, fontWeight: '700', marginTop: 14 }}>
                  {playlist?.name}
                </Text>
                <Text style={{ color: colors.textDim, fontSize: 12, marginTop: 2 }}>
                  {trackCountLabel(tracks.length)} · long-press to reorder
                </Text>
              </View>
              <PlayShuffleBar tracks={tracks} />
            </View>
          }
          renderItem={({ item, index }) => (
            <DraggableRow item={item} index={index} tracks={tracks} colors={colors} menu={menu} />
          )}
          contentContainerStyle={{ paddingBottom: 24 }}
        />
      )}
      <SheetMenu
        visible={menuOpen}
        onClose={() => setMenuOpen(false)}
        title={playlist?.name}
        items={[
          { key: 'rename', label: 'Rename playlist', icon: 'pencil-outline', onPress: () => setRenameOpen(true) },
          { key: 'delete', label: 'Delete playlist', icon: 'trash-outline', destructive: true, onPress: confirmDelete },
        ]}
      />
      <InputDialog
        visible={renameOpen}
        title="Rename playlist"
        placeholder="Playlist name"
        initialValue={playlist?.name ?? ''}
        onClose={() => setRenameOpen(false)}
        onSubmit={async (name) => {
          await renamePlaylist(String(id), name);
          bumpLibrary();
        }}
      />
      {menu.element}
    </View>
  );
}
