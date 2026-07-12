import { useCallback, useEffect, useRef, useState } from 'react';
import { Pressable, ScrollView, Text, TextInput, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useFocusEffect, useRouter } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { TrackRow } from '../../components/TrackRow';
import { TrackArt } from '../../components/TrackArt';
import { EmptyState } from '../../components/EmptyState';
import { useTrackMenu } from '../../components/TrackMenu';
import { useTheme } from '../../theme/useTheme';
import { useLibraryStore } from '../../stores/libraryStore';
import { searchTracks, albums as allAlbums, artists as allArtists, storageStats } from '../../db/trackRepo';
import { allPlaylists } from '../../db/playlistRepo';
import { playContext } from '../../player/playerService';
import { trackCountLabel } from '../../utils/format';

// Solid card tints that read well on both themes (white text on all).
const BROWSE_CARDS = [
  { key: 'songs', label: 'Songs', icon: 'musical-notes', color: '#27856A', to: '/library/songs' },
  { key: 'albums', label: 'Albums', icon: 'disc', color: '#8D67AB', to: '/library/albums' },
  { key: 'artists', label: 'Artists', icon: 'person', color: '#BA5D07', to: '/library/artists' },
  { key: 'playlists', label: 'Playlists', icon: 'list', color: '#E8115B', to: '/library' },
];

function BrowseGrid({ counts, colors, router }) {
  const countFor = (key) =>
    key === 'songs' ? trackCountLabel(counts.songs)
      : key === 'albums' ? `${counts.albums} albums`
        : key === 'artists' ? `${counts.artists} artists`
          : `${counts.playlists} playlists`;
  return (
    <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={{ padding: 16, paddingBottom: 24 }}>
      <Text style={{ color: colors.text, fontSize: 16, fontWeight: '700', marginBottom: 12 }}>
        Browse your library
      </Text>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'space-between', gap: 12 }}>
        {BROWSE_CARDS.map((card) => (
          <Pressable
            key={card.key}
            onPress={() => router.push(card.to)}
            style={({ pressed }) => ({
              width: '47.5%',
              height: 92,
              borderRadius: 10,
              backgroundColor: card.color,
              padding: 12,
              overflow: 'hidden',
              opacity: pressed ? 0.85 : 1,
            })}
          >
            <Text style={{ color: '#fff', fontSize: 16, fontWeight: '700' }}>{card.label}</Text>
            <Text style={{ color: 'rgba(255,255,255,0.85)', fontSize: 12, marginTop: 2 }}>
              {countFor(card.key)}
            </Text>
            <Ionicons
              name={card.icon}
              size={54}
              color="rgba(255,255,255,0.35)"
              style={{ position: 'absolute', right: -8, bottom: -10, transform: [{ rotate: '20deg' }] }}
            />
          </Pressable>
        ))}
      </View>
      <Text style={{ color: colors.textDim, fontSize: 13, marginTop: 20, lineHeight: 19 }}>
        Or type above to search everything you've downloaded — songs, artists, albums and playlists.
      </Text>
    </ScrollView>
  );
}

export default function SearchScreen() {
  const colors = useTheme();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const tick = useLibraryStore((s) => s.tick);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState(null);
  const [counts, setCounts] = useState(null);
  const menu = useTrackMenu();
  const debounceRef = useRef(null);

  useFocusEffect(
    useCallback(() => {
      let alive = true;
      Promise.all([storageStats(), allAlbums(), allArtists(), allPlaylists()]).then(
        ([stats, albums, artists, playlists]) => {
          if (!alive) return;
          setCounts({
            songs: stats?.track_count ?? 0,
            albums: albums.length,
            artists: artists.length,
            playlists: playlists.length,
          });
        }
      );
      return () => {
        alive = false;
      };
    }, [tick])
  );

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
        counts && counts.songs === 0 && counts.playlists === 0 ? (
          <EmptyState
            icon="search"
            title="Nothing to search yet"
            message="Add music first — from your server or from files on this device."
            actionLabel="Add from server"
            onAction={() => router.push('/import')}
            secondaryActionLabel="Import from this device"
            onSecondaryAction={() => router.push('/import-local')}
          />
        ) : (
          <BrowseGrid counts={counts ?? { songs: 0, albums: 0, artists: 0, playlists: 0 }} colors={colors} router={router} />
        )
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
