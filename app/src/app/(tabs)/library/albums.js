import { useCallback, useState } from 'react';
import { Pressable, Text, View } from 'react-native';
import { useRouter } from 'expo-router';
import { FlashList } from '@shopify/flash-list';
import { TrackArt } from '../../../components/TrackArt';
import { EmptyState } from '../../../components/EmptyState';
import { useTheme } from '../../../theme/useTheme';
import { useLibraryStore } from '../../../stores/libraryStore';
import { useLibraryReload } from '../../../library/useLibraryReload';
import { albums as loadAlbums } from '../../../db/trackRepo';

export default function AlbumsScreen() {
  const colors = useTheme();
  const router = useRouter();
  const tick = useLibraryStore((s) => s.tick);
  const [albums, setAlbums] = useState([]);

  useLibraryReload(
    useCallback(() => {
      let alive = true;
      loadAlbums().then((a) => alive && setAlbums(a));
      return () => {
        alive = false;
      };
    }, [tick])
  );

  if (albums.length === 0) {
    return (
      <View style={{ flex: 1, backgroundColor: colors.background }}>
        <EmptyState icon="disc" title="No albums yet" />
      </View>
    );
  }

  return (
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      <FlashList
        data={albums}
        numColumns={2}
        keyExtractor={(a) => `${a.album_artist}:${a.album}`}
        renderItem={({ item }) => (
          <Pressable
            onPress={() => router.push(`/library/album/${encodeURIComponent(`${item.album_artist}:::${item.album}`)}`)}
            style={({ pressed }) => ({ flex: 1, padding: 12, opacity: pressed ? 0.8 : 1 })}
          >
            <TrackArt track={item.art_path ? { art_path: item.art_path } : null} size={160} radius={8} />
            <Text numberOfLines={1} style={{ color: colors.text, fontSize: 14, fontWeight: '600', marginTop: 8 }}>
              {item.album}
            </Text>
            <Text numberOfLines={1} style={{ color: colors.textDim, fontSize: 12 }}>
              {item.album_artist}
            </Text>
          </Pressable>
        )}
        contentContainerStyle={{ paddingHorizontal: 4, paddingBottom: 24 }}
      />
    </View>
  );
}
