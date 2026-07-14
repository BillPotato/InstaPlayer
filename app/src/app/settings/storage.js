import { useCallback, useState } from 'react';
import { Alert, Text, View } from 'react-native';
import { FlashList } from '@shopify/flash-list';
import { TrackRow } from '../../components/TrackRow';
import { EmptyState } from '../../components/EmptyState';
import { useTheme } from '../../theme/useTheme';
import { useLibraryStore } from '../../stores/libraryStore';
import { useLibraryReload } from '../../library/useLibraryReload';
import { storageStats, tracksBySize } from '../../db/trackRepo';
import { deleteTrack } from '../../library/libraryActions';
import { formatBytes, trackCountLabel } from '../../utils/format';

export default function StorageScreen() {
  const colors = useTheme();
  const tick = useLibraryStore((s) => s.tick);
  const [stats, setStats] = useState(null);
  const [tracks, setTracks] = useState([]);

  useLibraryReload(
    useCallback(() => {
      let alive = true;
      Promise.all([storageStats(), tracksBySize()]).then(([s, t]) => {
        if (!alive) return;
        setStats(s);
        setTracks(t);
      });
      return () => {
        alive = false;
      };
    }, [tick])
  );

  const confirmDelete = (t) => {
    Alert.alert('Delete download?', `"${t.title}" (${formatBytes(t.file_size)}) will be removed from this device.`, [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Delete', style: 'destructive', onPress: () => deleteTrack(t) },
    ]);
  };

  return (
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      <View style={{ padding: 20, paddingBottom: 8 }}>
        <Text style={{ color: colors.text, fontSize: 28, fontWeight: '800' }}>
          {formatBytes(stats?.total_bytes ?? 0)}
        </Text>
        <Text style={{ color: colors.textDim, fontSize: 13, marginTop: 4 }}>
          {trackCountLabel(stats?.track_count ?? 0)} stored on this device — largest first
        </Text>
      </View>
      {tracks.length === 0 ? (
        <EmptyState icon="folder-open-outline" title="Nothing downloaded" />
      ) : (
        <FlashList
          data={tracks}
          keyExtractor={(t) => t.id}
          renderItem={({ item }) => (
            <TrackRow
              track={item}
              subtitle={`${item.artist} · ${formatBytes(item.file_size)}`}
              onPress={() => confirmDelete(item)}
              onMenuPress={() => confirmDelete(item)}
            />
          )}
          contentContainerStyle={{ paddingBottom: 24 }}
        />
      )}
    </View>
  );
}
