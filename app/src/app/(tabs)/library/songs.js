import { useCallback, useState } from 'react';
import { View } from 'react-native';
import { useFocusEffect } from 'expo-router';
import { FlashList } from '@shopify/flash-list';
import { TrackRow } from '../../../components/TrackRow';
import { EmptyState } from '../../../components/EmptyState';
import { PlayShuffleBar } from '../../../components/PlayShuffleBar';
import { useTrackMenu } from '../../../components/TrackMenu';
import { useTheme } from '../../../theme/useTheme';
import { useLibraryStore } from '../../../stores/libraryStore';
import { allTracks } from '../../../db/trackRepo';
import { playContext } from '../../../player/playerService';

export default function SongsScreen() {
  const colors = useTheme();
  const tick = useLibraryStore((s) => s.tick);
  const [tracks, setTracks] = useState([]);
  const menu = useTrackMenu();

  useFocusEffect(
    useCallback(() => {
      let alive = true;
      allTracks().then((t) => alive && setTracks(t));
      return () => {
        alive = false;
      };
    }, [tick])
  );

  return (
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      {tracks.length === 0 ? (
        <EmptyState title="No songs yet" message="Music you add appears here." />
      ) : (
        <FlashList
          data={tracks}
          keyExtractor={(t) => t.id}
          ListHeaderComponent={<PlayShuffleBar tracks={tracks} />}
          renderItem={({ item, index }) => (
            <TrackRow
              track={item}
              onPress={() => playContext(tracks, index)}
              onLongPress={() => menu.open(item)}
              onMenuPress={() => menu.open(item)}
            />
          )}
          contentContainerStyle={{ paddingBottom: 24 }}
        />
      )}
      {menu.element}
    </View>
  );
}
