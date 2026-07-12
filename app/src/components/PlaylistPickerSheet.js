import { useEffect, useState } from 'react';
import { Modal, Pressable, ScrollView, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useTheme } from '../theme/useTheme';
import {
  allPlaylists, createPlaylist, addTracksToPlaylist, playlistIdsContainingTrack,
} from '../db/playlistRepo';
import { bumpLibrary } from '../stores/libraryStore';
import { InputDialog } from './InputDialog';
import { notify } from '../utils/notify';

// Bottom sheet for adding one or more tracks to a playlist.
export function PlaylistPickerSheet({ visible, trackIds, onClose }) {
  const colors = useTheme();
  const insets = useSafeAreaInsets();
  const [playlists, setPlaylists] = useState([]);
  const [containing, setContaining] = useState(new Set());
  const [showNew, setShowNew] = useState(false);

  useEffect(() => {
    if (!visible) return;
    allPlaylists().then(setPlaylists).catch(() => setPlaylists([]));
    // Mark playlists that already contain the song (single-track case).
    if (trackIds.length === 1) {
      playlistIdsContainingTrack(trackIds[0]).then(setContaining).catch(() => setContaining(new Set()));
    } else {
      setContaining(new Set());
    }
  }, [visible, trackIds]);

  const addTo = async (playlistId, name) => {
    onClose();
    const added = await addTracksToPlaylist(playlistId, trackIds);
    if (added > 0) {
      bumpLibrary();
      notify(`Added to ${name}`);
    } else {
      notify(`Already in ${name}`);
    }
  };

  return (
    <>
      <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
        <Pressable style={{ flex: 1, backgroundColor: 'rgba(0,0,0,0.55)' }} onPress={onClose} />
        <View
          style={{
            backgroundColor: colors.surface,
            borderTopLeftRadius: 16,
            borderTopRightRadius: 16,
            paddingBottom: insets.bottom + 12,
            maxHeight: '60%',
          }}
        >
          <Text style={{ color: colors.text, fontSize: 16, fontWeight: '600', padding: 20, paddingBottom: 8 }}>
            Add to playlist
          </Text>
          <Pressable
            android_ripple={{ color: colors.surfaceHigh }}
            onPress={() => {
              onClose();
              setTimeout(() => setShowNew(true), 150);
            }}
            style={{ flexDirection: 'row', alignItems: 'center', paddingHorizontal: 20, paddingVertical: 12 }}
          >
            <View
              style={{
                width: 40, height: 40, borderRadius: 8, backgroundColor: colors.surfaceHigh,
                alignItems: 'center', justifyContent: 'center', marginRight: 14,
              }}
            >
              <Ionicons name="add" size={24} color={colors.text} />
            </View>
            <Text style={{ color: colors.text, fontSize: 15, fontWeight: '500' }}>New playlist</Text>
          </Pressable>
          <ScrollView bounces={false}>
            {playlists.map((p) => (
              <Pressable
                key={p.id}
                android_ripple={{ color: colors.surfaceHigh }}
                onPress={() => addTo(p.id, p.name)}
                style={{ flexDirection: 'row', alignItems: 'center', paddingHorizontal: 20, paddingVertical: 12 }}
              >
                <View
                  style={{
                    width: 40, height: 40, borderRadius: 8, backgroundColor: colors.surfaceHigh,
                    alignItems: 'center', justifyContent: 'center', marginRight: 14,
                  }}
                >
                  <Ionicons name="musical-notes" size={18} color={colors.textDim} />
                </View>
                <View style={{ flex: 1 }}>
                  <Text numberOfLines={1} style={{ color: colors.text, fontSize: 15 }}>{p.name}</Text>
                  <Text style={{ color: colors.textDim, fontSize: 12 }}>{p.track_count} songs</Text>
                </View>
                {containing.has(p.id) ? (
                  <Ionicons name="checkmark-circle" size={20} color={colors.accent} />
                ) : null}
              </Pressable>
            ))}
          </ScrollView>
        </View>
      </Modal>
      <InputDialog
        visible={showNew}
        title="New playlist"
        placeholder="Playlist name"
        submitLabel="Create"
        onClose={() => setShowNew(false)}
        onSubmit={async (name) => {
          const id = await createPlaylist(name);
          await addTracksToPlaylist(id, trackIds);
          bumpLibrary();
          notify(`Added to ${name}`);
        }}
      />
    </>
  );
}
