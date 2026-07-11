import { useCallback, useState } from 'react';
import { Pressable, ScrollView, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useFocusEffect, useRouter } from 'expo-router';
import { ScreenHeader } from '../../../components/ScreenHeader';
import { TrackArt } from '../../../components/TrackArt';
import { SheetMenu } from '../../../components/SheetMenu';
import { InputDialog } from '../../../components/InputDialog';
import { useTheme } from '../../../theme/useTheme';
import { useLibraryStore, bumpLibrary } from '../../../stores/libraryStore';
import { useImportStore } from '../../../stores/importStore';
import { storageStats, albums, artists } from '../../../db/trackRepo';
import { allPlaylists, createPlaylist } from '../../../db/playlistRepo';
import { trackCountLabel } from '../../../utils/format';

function Row({ icon, label, sublabel, onPress, colors }) {
  return (
    <Pressable
      onPress={onPress}
      android_ripple={{ color: colors.surfaceHigh }}
      style={{ flexDirection: 'row', alignItems: 'center', paddingHorizontal: 16, paddingVertical: 12 }}
    >
      <View
        style={{
          width: 48, height: 48, borderRadius: 8, backgroundColor: colors.surfaceHigh,
          alignItems: 'center', justifyContent: 'center',
        }}
      >
        <Ionicons name={icon} size={22} color={colors.accent} />
      </View>
      <View style={{ marginLeft: 12, flex: 1 }}>
        <Text style={{ color: colors.text, fontSize: 16, fontWeight: '600' }}>{label}</Text>
        <Text style={{ color: colors.textDim, fontSize: 13, marginTop: 2 }}>{sublabel}</Text>
      </View>
      <Ionicons name="chevron-forward" size={18} color={colors.textDim} />
    </Pressable>
  );
}

export default function LibraryScreen() {
  const colors = useTheme();
  const router = useRouter();
  const tick = useLibraryStore((s) => s.tick);
  const importPhase = useImportStore((s) => s.phase);
  const importName = useImportStore((s) => s.name);
  const saved = useImportStore((s) => s.saved);
  const total = useImportStore((s) => s.total);
  const [counts, setCounts] = useState({ tracks: 0, albums: 0, artists: 0, playlists: 0 });
  const [playlists, setPlaylists] = useState([]);
  const [addOpen, setAddOpen] = useState(false);
  const [newPlaylistOpen, setNewPlaylistOpen] = useState(false);

  useFocusEffect(
    useCallback(() => {
      let alive = true;
      Promise.all([storageStats(), albums(), artists(), allPlaylists()]).then(([stats, al, ar, pl]) => {
        if (!alive) return;
        setCounts({ tracks: stats?.track_count ?? 0, albums: al.length, artists: ar.length, playlists: pl.length });
        setPlaylists(pl);
      });
      return () => {
        alive = false;
      };
    }, [tick])
  );

  const importActive = ['creating', 'active', 'draining', 'cleanup'].includes(importPhase);

  return (
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      <ScreenHeader
        title="Your Library"
        right={
          <Pressable onPress={() => setAddOpen(true)} hitSlop={8} style={{ padding: 6 }}>
            <Ionicons name="add" size={26} color={colors.text} />
          </Pressable>
        }
      />
      <ScrollView contentContainerStyle={{ paddingBottom: 24 }}>
        {importActive ? (
          <Pressable
            onPress={() => router.push('/import')}
            style={{
              marginHorizontal: 16, marginBottom: 8, backgroundColor: colors.surface,
              borderRadius: 10, padding: 12, flexDirection: 'row', alignItems: 'center',
            }}
          >
            <Ionicons name="cloud-download-outline" size={20} color={colors.accent} />
            <View style={{ marginLeft: 10, flex: 1 }}>
              <Text numberOfLines={1} style={{ color: colors.text, fontSize: 14, fontWeight: '600' }}>
                Importing{importName ? ` “${importName}”` : ''}…
              </Text>
              <Text style={{ color: colors.textDim, fontSize: 12 }}>
                {saved}{total ? ` of ${total}` : ''} saved — tap for details
              </Text>
            </View>
            <Ionicons name="chevron-forward" size={16} color={colors.textDim} />
          </Pressable>
        ) : null}

        <Row icon="musical-notes" label="Songs" sublabel={trackCountLabel(counts.tracks)} onPress={() => router.push('/library/songs')} colors={colors} />
        <Row icon="disc" label="Albums" sublabel={`${counts.albums} albums`} onPress={() => router.push('/library/albums')} colors={colors} />
        <Row icon="person" label="Artists" sublabel={`${counts.artists} artists`} onPress={() => router.push('/library/artists')} colors={colors} />

        <Text style={{ color: colors.text, fontSize: 18, fontWeight: '700', paddingHorizontal: 16, marginTop: 16, marginBottom: 4 }}>
          Playlists
        </Text>
        {playlists.length === 0 ? (
          <Text style={{ color: colors.textDim, paddingHorizontal: 16, paddingVertical: 8, fontSize: 14 }}>
            No playlists yet. Tap + to create one.
          </Text>
        ) : (
          playlists.map((p) => (
            <Pressable
              key={p.id}
              onPress={() => router.push(`/library/playlist/${p.id}`)}
              android_ripple={{ color: colors.surfaceHigh }}
              style={{ flexDirection: 'row', alignItems: 'center', paddingHorizontal: 16, paddingVertical: 8 }}
            >
              <TrackArt track={p.art_path ? { art_path: p.art_path } : null} size={48} radius={6} />
              <View style={{ marginLeft: 12, flex: 1 }}>
                <Text numberOfLines={1} style={{ color: colors.text, fontSize: 15, fontWeight: '500' }}>{p.name}</Text>
                <Text style={{ color: colors.textDim, fontSize: 13 }}>{trackCountLabel(p.track_count)}</Text>
              </View>
              <Ionicons name="chevron-forward" size={16} color={colors.textDim} />
            </Pressable>
          ))
        )}
      </ScrollView>

      <SheetMenu
        visible={addOpen}
        onClose={() => setAddOpen(false)}
        title="Add"
        items={[
          { key: 'import', label: 'Add music from your server', icon: 'cloud-download-outline', onPress: () => router.push('/import') },
          { key: 'local', label: 'Import from this device', icon: 'phone-portrait-outline', onPress: () => router.push('/import-local') },
          { key: 'playlist', label: 'New playlist', icon: 'add-circle-outline', onPress: () => setNewPlaylistOpen(true) },
        ]}
      />
      <InputDialog
        visible={newPlaylistOpen}
        title="New playlist"
        placeholder="Playlist name"
        submitLabel="Create"
        onClose={() => setNewPlaylistOpen(false)}
        onSubmit={async (name) => {
          const id = await createPlaylist(name);
          bumpLibrary();
          router.push(`/library/playlist/${id}`);
        }}
      />
    </View>
  );
}
