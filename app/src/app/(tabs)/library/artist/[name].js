import { useCallback, useMemo, useState } from 'react';
import { ScrollView, Text, View } from 'react-native';
import { useLocalSearchParams, useNavigation } from 'expo-router';
import { TrackArt } from '../../../../components/TrackArt';
import { TrackRow } from '../../../../components/TrackRow';
import { useTrackMenu } from '../../../../components/TrackMenu';
import { PlayShuffleBar } from '../../../../components/PlayShuffleBar';
import { useTheme } from '../../../../theme/useTheme';
import { useLibraryStore } from '../../../../stores/libraryStore';
import { useLibraryReload } from '../../../../library/useLibraryReload';
import { artistTracks } from '../../../../db/trackRepo';
import { playContext } from '../../../../player/playerService';
import { trackCountLabel } from '../../../../utils/format';

export default function ArtistScreen() {
  const colors = useTheme();
  const navigation = useNavigation();
  const { name } = useLocalSearchParams();
  const tick = useLibraryStore((s) => s.tick);
  const [tracks, setTracks] = useState([]);
  const menu = useTrackMenu();

  const artist = useMemo(() => decodeURIComponent(String(name || '')), [name]);

  useLibraryReload(
    useCallback(() => {
      let alive = true;
      navigation.setOptions({ title: artist });
      artistTracks(artist).then((t) => alive && setTracks(t));
      return () => {
        alive = false;
      };
    }, [artist, tick, navigation])
  );

  return (
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      <ScrollView contentContainerStyle={{ paddingBottom: 24 }}>
        <View style={{ alignItems: 'center', paddingTop: 16 }}>
          <TrackArt track={tracks.find((t) => t.art_path) || null} size={160} radius={80} />
          <Text style={{ color: colors.text, fontSize: 20, fontWeight: '700', marginTop: 14 }}>{artist}</Text>
          <Text style={{ color: colors.textDim, fontSize: 12, marginTop: 2 }}>{trackCountLabel(tracks.length)}</Text>
        </View>
        <PlayShuffleBar tracks={tracks} />
        {tracks.map((t, i) => (
          <TrackRow
            key={t.id}
            track={t}
            subtitle={t.album}
            onPress={() => playContext(tracks, i)}
            onLongPress={() => menu.open(t)}
            onMenuPress={() => menu.open(t)}
          />
        ))}
      </ScrollView>
      {menu.element}
    </View>
  );
}
