import { useCallback, useState } from 'react';
import { Pressable, ScrollView, Text, View } from 'react-native';
import { useFocusEffect, useRouter } from 'expo-router';
import { ScreenHeader } from '../../components/ScreenHeader';
import { TrackArt } from '../../components/TrackArt';
import { TrackRow } from '../../components/TrackRow';
import { EmptyState } from '../../components/EmptyState';
import { useTrackMenu } from '../../components/TrackMenu';
import { useTheme } from '../../theme/useTheme';
import { useLibraryStore } from '../../stores/libraryStore';
import { recentlyPlayed } from '../../db/historyRepo';
import { recentlyAdded } from '../../db/trackRepo';
import { playContext } from '../../player/playerService';

export default function HomeScreen() {
  const colors = useTheme();
  const router = useRouter();
  const tick = useLibraryStore((s) => s.tick);
  const [played, setPlayed] = useState([]);
  const [added, setAdded] = useState([]);
  const menu = useTrackMenu();

  useFocusEffect(
    useCallback(() => {
      let alive = true;
      Promise.all([recentlyPlayed(15), recentlyAdded(25)]).then(([p, a]) => {
        if (!alive) return;
        setPlayed(p);
        setAdded(a);
      });
      return () => {
        alive = false;
      };
    }, [tick])
  );

  const empty = played.length === 0 && added.length === 0;

  return (
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      <ScreenHeader title="Home" />
      {empty ? (
        <EmptyState
          title="Nothing here yet"
          message="Add music from your server, or import audio files already on this device."
          actionLabel="Add from server"
          onAction={() => router.push('/import')}
          secondaryActionLabel="Import from this device"
          onSecondaryAction={() => router.push('/import-local')}
        />
      ) : (
        <ScrollView contentContainerStyle={{ paddingBottom: 24 }}>
          {played.length > 0 ? (
            <>
              <Text style={{ color: colors.text, fontSize: 18, fontWeight: '700', paddingHorizontal: 16, marginTop: 8 }}>
                Recently played
              </Text>
              <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ paddingHorizontal: 16, paddingTop: 12, gap: 12 }}>
                {played.map((t, i) => (
                  <Pressable key={t.id} onPress={() => playContext(played, i)} onLongPress={() => menu.open(t)} style={{ width: 120 }}>
                    <TrackArt track={t} size={120} radius={8} />
                    <Text numberOfLines={1} style={{ color: colors.text, fontSize: 13, fontWeight: '600', marginTop: 6 }}>
                      {t.title}
                    </Text>
                    <Text numberOfLines={1} style={{ color: colors.textDim, fontSize: 12 }}>
                      {t.artist}
                    </Text>
                  </Pressable>
                ))}
              </ScrollView>
            </>
          ) : null}
          {added.length > 0 ? (
            <>
              <Text style={{ color: colors.text, fontSize: 18, fontWeight: '700', paddingHorizontal: 16, marginTop: 20, marginBottom: 8 }}>
                Recently added
              </Text>
              {added.map((t, i) => (
                <TrackRow
                  key={t.id}
                  track={t}
                  onPress={() => playContext(added, i)}
                  onLongPress={() => menu.open(t)}
                  onMenuPress={() => menu.open(t)}
                />
              ))}
            </>
          ) : null}
        </ScrollView>
      )}
      {menu.element}
    </View>
  );
}
