import { useEffect, useMemo, useRef, useState } from 'react';
import { Pressable, ScrollView, Text, TextInput, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { TrackRow } from '../../components/TrackRow';
import { TrackArt } from '../../components/TrackArt';
import { EmptyState } from '../../components/EmptyState';
import { useTrackMenu } from '../../components/TrackMenu';
import { useTheme } from '../../theme/useTheme';
import { useLibraryStore } from '../../stores/libraryStore';
import { searchTracks, albums as allAlbums, artists as allArtists } from '../../db/trackRepo';
import { allPlaylists } from '../../db/playlistRepo';
import { playContext } from '../../player/playerService';
import { trackCountLabel } from '../../utils/format';

export default function SearchScreen() {
  const colors = useTheme();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const tick = useLibraryStore((s) => s.tick);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState(null);
  const menu = useTrackMenu();
  const debounceRef = useRef(null);

  useEffect(() => {
    const q = query.trim();
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (!q) {
      setResults(null);
      return undefined;
    }
    debounceRef.current = setTimeout(async () => {
      const lower = q.toLowerCase();
      const [tracks, albums, artists, playlists] = await Promise.all([
        searchTracks(q),
        allAlbums(),
        allArtists(),
        allPlaylists(),
      ]);
      setResults({
        q,
        tracks,
        albums: albums.filter((a) => a.album.toLowerCase().includes(lower) || a.album_artist.toLowerCase().includes(lower)).slice(0, 10),
        artists: artists.filter((a) => a.artist.toLowerCase().includes(lower)).slice(0, 10),
        playlists: playlists.filter((p) => p.name.toLowerCase().includes(lower)).slice(0, 10),
      });
    }, 250);
    return () => clearTimeout(debounceRef.current);
  }, [query, tick]);

  const sectionTitle = (label) => (
    <Text style={{ color: colors.text, fontSize: 16, fontWeight: '700', paddingHorizontal: 16, marginTop: 16, marginBottom: 4 }}>
      {label}
    </Text>
  );

  return (
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      <View style={{ paddingTop: insets.top + 8, paddingHorizontal: 16, paddingBottom: 8 }}>
        <Text style={{ color: colors.text, fontSize: 24, fontWeight: '700', marginBottom: 12 }}>Search</Text>
        <View
          style={{
            flexDirection: 'row', alignItems: 'center', backgroundColor: colors.surfaceHigh,
            borderRadius: 8, paddingHorizontal: 12,
          }}
        >
          <Ionicons name="search" size={18} color={colors.textDim} />
          <TextInput
            value={query}
            onChangeText={setQuery}
            placeholder="Songs, artists, albums…"
            placeholderTextColor={colors.textDim}
            autoCorrect={false}
            style={{ flex: 1, color: colors.text, paddingVertical: 10, paddingHorizontal: 8, fontSize: 15 }}
          />
          {query ? (
            <Pressable onPress={() => setQuery('')} hitSlop={8}>
              <Ionicons name="close-circle" size={18} color={colors.textDim} />
            </Pressable>
          ) : null}
        </View>
      </View>

      {!results ? (
        <EmptyState icon="search" title="Search your library" message="Find songs, albums, artists and playlists you have downloaded." />
      ) : (
        <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={{ paddingBottom: 24 }}>
          {results.tracks.length === 0 && results.albums.length === 0 && results.artists.length === 0 && results.playlists.length === 0 ? (
            <View style={{ paddingTop: 48 }}>
              <EmptyState icon="sad-outline" title={`No results for “${results.q}”`} />
            </View>
          ) : (
            <>
              {results.tracks.length > 0 ? (
                <>
                  {sectionTitle('Songs')}
                  {results.tracks.map((t, i) => (
                    <TrackRow key={t.id} track={t} onPress={() => playContext(results.tracks, i)} onLongPress={() => menu.open(t)} onMenuPress={() => menu.open(t)} />
                  ))}
                </>
              ) : null}
              {results.albums.length > 0 ? (
                <>
                  {sectionTitle('Albums')}
                  {results.albums.map((a) => (
                    <Pressable
                      key={`${a.album_artist}:${a.album}`}
                      onPress={() => router.push(`/library/album/${encodeURIComponent(`${a.album_artist}:::${a.album}`)}`)}
                      android_ripple={{ color: colors.surfaceHigh }}
                      style={{ flexDirection: 'row', alignItems: 'center', paddingHorizontal: 16, paddingVertical: 8 }}
                    >
                      <TrackArt track={a.art_path ? { art_path: a.art_path } : null} size={48} radius={6} />
                      <View style={{ marginLeft: 12, flex: 1 }}>
                        <Text numberOfLines={1} style={{ color: colors.text, fontSize: 15, fontWeight: '500' }}>{a.album}</Text>
                        <Text numberOfLines={1} style={{ color: colors.textDim, fontSize: 13 }}>
                          Album — {a.album_artist}
                        </Text>
                      </View>
                    </Pressable>
                  ))}
                </>
              ) : null}
              {results.artists.length > 0 ? (
                <>
                  {sectionTitle('Artists')}
                  {results.artists.map((a) => (
                    <Pressable
                      key={a.artist}
                      onPress={() => router.push(`/library/artist/${encodeURIComponent(a.artist)}`)}
                      android_ripple={{ color: colors.surfaceHigh }}
                      style={{ flexDirection: 'row', alignItems: 'center', paddingHorizontal: 16, paddingVertical: 8 }}
                    >
                      <TrackArt track={a.art_path ? { art_path: a.art_path } : null} size={48} radius={24} />
                      <View style={{ marginLeft: 12, flex: 1 }}>
                        <Text numberOfLines={1} style={{ color: colors.text, fontSize: 15, fontWeight: '500' }}>{a.artist}</Text>
                        <Text style={{ color: colors.textDim, fontSize: 13 }}>Artist — {trackCountLabel(a.track_count)}</Text>
                      </View>
                    </Pressable>
                  ))}
                </>
              ) : null}
              {results.playlists.length > 0 ? (
                <>
                  {sectionTitle('Playlists')}
                  {results.playlists.map((p) => (
                    <Pressable
                      key={p.id}
                      onPress={() => router.push(`/library/playlist/${p.id}`)}
                      android_ripple={{ color: colors.surfaceHigh }}
                      style={{ flexDirection: 'row', alignItems: 'center', paddingHorizontal: 16, paddingVertical: 8 }}
                    >
                      <TrackArt track={p.art_path ? { art_path: p.art_path } : null} size={48} radius={6} />
                      <View style={{ marginLeft: 12, flex: 1 }}>
                        <Text numberOfLines={1} style={{ color: colors.text, fontSize: 15, fontWeight: '500' }}>{p.name}</Text>
                        <Text style={{ color: colors.textDim, fontSize: 13 }}>Playlist — {trackCountLabel(p.track_count)}</Text>
                      </View>
                    </Pressable>
                  ))}
                </>
              ) : null}
            </>
          )}
        </ScrollView>
      )}
      {menu.element}
    </View>
  );
}
