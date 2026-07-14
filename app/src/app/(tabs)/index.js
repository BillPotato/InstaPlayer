import { useCallback, useMemo, useState } from 'react';
import { Pressable, ScrollView, Text, View } from 'react-native';
import { useRouter } from 'expo-router';
import { ScreenHeader } from '../../components/ScreenHeader';
import { TrackArt } from '../../components/TrackArt';
import { TrackRow } from '../../components/TrackRow';
import { EmptyState } from '../../components/EmptyState';
import { useTrackMenu } from '../../components/TrackMenu';
import { useTheme } from '../../theme/useTheme';
import { useLibraryStore } from '../../stores/libraryStore';
import { useLibraryReload } from '../../library/useLibraryReload';
import { recentlyPlayed } from '../../db/historyRepo';
import { recentlyAdded, albums as loadAlbums, artists as loadArtists } from '../../db/trackRepo';
import { allPlaylists } from '../../db/playlistRepo';
import { playContext } from '../../player/playerService';
import { trackCountLabel } from '../../utils/format';

const albumKey = (a) => encodeURIComponent(`${a.album_artist}:::${a.album}`);

function greeting() {
  const h = new Date().getHours();
  if (h < 5) return 'Good night';
  if (h < 12) return 'Good morning';
  if (h < 18) return 'Good afternoon';
  return 'Good evening';
}

// Spotify-style quick-pick pill: small art + label, two per row.
function QuickPick({ item, colors, onPress }) {
  return (
    <Pressable
      onPress={onPress}
      android_ripple={{ color: colors.surfaceHigh }}
      style={({ pressed }) => ({
        flexDirection: 'row',
        alignItems: 'center',
        backgroundColor: colors.surface,
        borderRadius: 6,
        overflow: 'hidden',
        width: '48.5%',
        opacity: pressed ? 0.8 : 1,
      })}
    >
      <TrackArt track={item.art_path ? { art_path: item.art_path } : null} size={52} radius={0} iconSize={22} />
      <Text numberOfLines={2} style={{ color: colors.text, fontSize: 13, fontWeight: '700', flex: 1, marginHorizontal: 8 }}>
        {item.label}
      </Text>
    </Pressable>
  );
}

function SectionHeader({ title, onSeeAll, colors }) {
  return (
    <View style={{ flexDirection: 'row', alignItems: 'baseline', justifyContent: 'space-between', paddingHorizontal: 16, marginTop: 24, marginBottom: 12 }}>
      <Text style={{ color: colors.text, fontSize: 19, fontWeight: '700' }}>{title}</Text>
      {onSeeAll ? (
        <Pressable onPress={onSeeAll} hitSlop={8}>
          <Text style={{ color: colors.textDim, fontSize: 13, fontWeight: '600' }}>See all</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

function Shelf({ children }) {
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ paddingHorizontal: 16, gap: 14 }}>
      {children}
    </ScrollView>
  );
}

function Card({ artTrack, title, subtitle, round, onPress, onLongPress, colors }) {
  return (
    <Pressable onPress={onPress} onLongPress={onLongPress} style={({ pressed }) => ({ width: 120, opacity: pressed ? 0.8 : 1 })}>
      <View style={{ alignItems: round ? 'center' : 'stretch' }}>
        <TrackArt track={artTrack} size={120} radius={round ? 60 : 8} iconSize={40} />
        <Text
          numberOfLines={1}
          style={{ color: colors.text, fontSize: 13, fontWeight: '600', marginTop: 6, textAlign: round ? 'center' : 'left' }}
        >
          {title}
        </Text>
        {subtitle ? (
          <Text numberOfLines={1} style={{ color: colors.textDim, fontSize: 12, textAlign: round ? 'center' : 'left' }}>
            {subtitle}
          </Text>
        ) : null}
      </View>
    </Pressable>
  );
}

export default function HomeScreen() {
  const colors = useTheme();
  const router = useRouter();
  const tick = useLibraryStore((s) => s.tick);
  const [data, setData] = useState({ played: [], added: [], playlists: [], albums: [], artists: [] });
  const menu = useTrackMenu();

  useLibraryReload(
    useCallback(() => {
      let alive = true;
      Promise.all([recentlyPlayed(15), recentlyAdded(10), allPlaylists(), loadAlbums(), loadArtists()]).then(
        ([played, added, playlists, albums, artists]) => {
          if (alive) setData({ played, added, playlists, albums, artists });
        }
      );
      return () => {
        alive = false;
      };
    }, [tick])
  );

  const { played, added, playlists, albums, artists } = data;
  const empty = added.length === 0 && played.length === 0;

  // Quick picks: All songs + freshest playlists, topped up with the albums
  // behind the most recent listens/additions.
  const quickPicks = useMemo(() => {
    const picks = [];
    if (added.length || played.length) {
      picks.push({ key: 'songs', label: 'All songs', art_path: null, to: '/library/songs' });
    }
    for (const p of playlists.slice(0, 3)) {
      picks.push({ key: `pl-${p.id}`, label: p.name, art_path: p.art_path, to: `/library/playlist/${p.id}` });
    }
    const seen = new Set();
    for (const t of [...played, ...added]) {
      if (picks.length >= 6) break;
      const k = `${t.album_artist}:::${t.album}`;
      if (seen.has(k)) continue;
      seen.add(k);
      picks.push({
        key: `al-${k}`,
        label: t.album,
        art_path: t.art_path,
        to: `/library/album/${encodeURIComponent(k)}`,
      });
    }
    return picks.slice(0, 6);
  }, [played, added, playlists]);

  return (
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      <ScreenHeader title={greeting()} />
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
          {/* Quick picks */}
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', paddingHorizontal: 16, gap: 8, justifyContent: 'space-between' }}>
            {quickPicks.map((q) => (
              <QuickPick key={q.key} item={q} colors={colors} onPress={() => router.push(q.to)} />
            ))}
          </View>

          {played.length > 0 ? (
            <>
              <SectionHeader title="Recently played" colors={colors} />
              <Shelf>
                {played.map((t, i) => (
                  <Card
                    key={t.id}
                    artTrack={t}
                    title={t.title}
                    subtitle={t.artist}
                    onPress={() => playContext(played, i)}
                    onLongPress={() => menu.open(t)}
                    colors={colors}
                  />
                ))}
              </Shelf>
            </>
          ) : null}

          {playlists.length > 0 ? (
            <>
              <SectionHeader title="Your playlists" onSeeAll={() => router.push('/library')} colors={colors} />
              <Shelf>
                {playlists.slice(0, 10).map((p) => (
                  <Card
                    key={p.id}
                    artTrack={p.art_path ? { art_path: p.art_path } : null}
                    title={p.name}
                    subtitle={trackCountLabel(p.track_count)}
                    onPress={() => router.push(`/library/playlist/${p.id}`)}
                    colors={colors}
                  />
                ))}
              </Shelf>
            </>
          ) : null}

          {albums.length > 0 ? (
            <>
              <SectionHeader title="Albums" onSeeAll={() => router.push('/library/albums')} colors={colors} />
              <Shelf>
                {albums.slice(0, 10).map((a) => (
                  <Card
                    key={`${a.album_artist}:${a.album}`}
                    artTrack={a.art_path ? { art_path: a.art_path } : null}
                    title={a.album}
                    subtitle={a.album_artist}
                    onPress={() => router.push(`/library/album/${albumKey(a)}`)}
                    colors={colors}
                  />
                ))}
              </Shelf>
            </>
          ) : null}

          {artists.length > 0 ? (
            <>
              <SectionHeader title="Artists" onSeeAll={() => router.push('/library/artists')} colors={colors} />
              <Shelf>
                {artists.slice(0, 10).map((a) => (
                  <Card
                    key={a.artist}
                    artTrack={a.art_path ? { art_path: a.art_path } : null}
                    title={a.artist}
                    subtitle={trackCountLabel(a.track_count)}
                    round
                    onPress={() => router.push(`/library/artist/${encodeURIComponent(a.artist)}`)}
                    colors={colors}
                  />
                ))}
              </Shelf>
            </>
          ) : null}

          {added.length > 0 ? (
            <>
              <SectionHeader title="Recently added" onSeeAll={() => router.push('/library/songs')} colors={colors} />
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
