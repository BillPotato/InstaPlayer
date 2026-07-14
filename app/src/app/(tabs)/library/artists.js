import { useCallback, useState } from 'react';
import { Pressable, Text, View } from 'react-native';
import { useRouter } from 'expo-router';
import { FlashList } from '@shopify/flash-list';
import { TrackArt } from '../../../components/TrackArt';
import { EmptyState } from '../../../components/EmptyState';
import { useTheme } from '../../../theme/useTheme';
import { useLibraryStore } from '../../../stores/libraryStore';
import { useLibraryReload } from '../../../library/useLibraryReload';
import { artists as loadArtists } from '../../../db/trackRepo';
import { trackCountLabel } from '../../../utils/format';

export default function ArtistsScreen() {
  const colors = useTheme();
  const router = useRouter();
  const tick = useLibraryStore((s) => s.tick);
  const [artists, setArtists] = useState([]);

  useLibraryReload(
    useCallback(() => {
      let alive = true;
      loadArtists().then((a) => alive && setArtists(a));
      return () => {
        alive = false;
      };
    }, [tick])
  );

  if (artists.length === 0) {
    return (
      <View style={{ flex: 1, backgroundColor: colors.background }}>
        <EmptyState icon="person" title="No artists yet" />
      </View>
    );
  }

  return (
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      <FlashList
        data={artists}
        keyExtractor={(a) => a.artist}
        renderItem={({ item }) => (
          <Pressable
            onPress={() => router.push(`/library/artist/${encodeURIComponent(item.artist)}`)}
            android_ripple={{ color: colors.surfaceHigh }}
            style={{ flexDirection: 'row', alignItems: 'center', paddingHorizontal: 16, paddingVertical: 8 }}
          >
            <TrackArt track={item.art_path ? { art_path: item.art_path } : null} size={52} radius={26} />
            <View style={{ marginLeft: 12, flex: 1 }}>
              <Text numberOfLines={1} style={{ color: colors.text, fontSize: 15, fontWeight: '500' }}>{item.artist}</Text>
              <Text style={{ color: colors.textDim, fontSize: 13 }}>
                {trackCountLabel(item.track_count)} · {item.album_count} album{item.album_count === 1 ? '' : 's'}
              </Text>
            </View>
          </Pressable>
        )}
        contentContainerStyle={{ paddingBottom: 24 }}
      />
    </View>
  );
}
