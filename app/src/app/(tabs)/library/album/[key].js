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
import { albumTracks } from '../../../../db/trackRepo';
import { playContext } from '../../../../player/playerService';
import { formatMs, trackCountLabel } from '../../../../utils/format';

export default function AlbumScreen() {
  const colors = useTheme();
  const navigation = useNavigation();
  const { key } = useLocalSearchParams();
  const tick = useLibraryStore((s) => s.tick);
  const [tracks, setTracks] = useState([]);
  const menu = useTrackMenu();

  const { albumArtist, album } = useMemo(() => {
    const decoded = decodeURIComponent(String(key || ''));
    const sep = decoded.indexOf(':::');
    return sep >= 0
      ? { albumArtist: decoded.slice(0, sep), album: decoded.slice(sep + 3) }
      : { albumArtist: '', album: decoded };
  }, [key]);

  useLibraryReload(
    useCallback(() => {
      let alive = true;
      navigation.setOptions({ title: album });
      albumTracks(albumArtist, album).then((t) => alive && setTracks(t));
      return () => {
        alive = false;
      };
    }, [albumArtist, album, tick, navigation])
  );

  const totalMs = tracks.reduce((sum, t) => sum + (t.duration_ms || 0), 0);

  return (
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      <ScrollView contentContainerStyle={{ paddingBottom: 24 }}>
        <View style={{ alignItems: 'center', paddingTop: 16 }}>
          <TrackArt track={tracks.find((t) => t.art_path) || null} size={200} radius={10} />
          <Text style={{ color: colors.text, fontSize: 20, fontWeight: '700', marginTop: 14, paddingHorizontal: 24, textAlign: 'center' }}>
            {album}
          </Text>
          <Text style={{ color: colors.textDim, fontSize: 14, marginTop: 4 }}>{albumArtist}</Text>
          <Text style={{ color: colors.textDim, fontSize: 12, marginTop: 2 }}>
            {trackCountLabel(tracks.length)} · {formatMs(totalMs)}
          </Text>
        </View>
        <PlayShuffleBar tracks={tracks} />
        {tracks.map((t, i) => (
          <TrackRow
            key={t.id}
            track={t}
            subtitle={t.track_number ? `${t.track_number}. ${t.artist}` : t.artist}
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
