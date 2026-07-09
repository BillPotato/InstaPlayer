import { useEffect, useState } from 'react';
import { Pressable, Text, View, useWindowDimensions } from 'react-native';
import Slider from '@react-native-community/slider';
import { Ionicons, MaterialIcons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { TrackArt } from '../components/TrackArt';
import { SheetMenu } from '../components/SheetMenu';
import { LyricsView } from '../components/LyricsView';
import { PlaylistPickerSheet } from '../components/PlaylistPickerSheet';
import { useTrackMenu } from '../components/TrackMenu';
import { useTheme } from '../theme/useTheme';
import { useCurrentTrack, usePlayerStore } from '../player/playerStore';
import { useLibraryStore } from '../stores/libraryStore';
import { isTrackInAnyPlaylist } from '../db/playlistRepo';
import {
  togglePlay, next, previous, seekTo, toggleShuffle, cycleRepeat,
  setRate, setSleepTimer, clearSleepTimer,
} from '../player/playerService';
import { formatTime } from '../utils/format';

const RATES = [0.5, 0.75, 1, 1.25, 1.5, 1.75, 2];

export default function PlayerScreen() {
  const colors = useTheme();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { width } = useWindowDimensions();
  const track = useCurrentTrack();
  const isPlaying = usePlayerStore((s) => s.isPlaying);
  const currentTime = usePlayerStore((s) => s.currentTime);
  const duration = usePlayerStore((s) => s.duration);
  const shuffle = usePlayerStore((s) => s.shuffle);
  const repeat = usePlayerStore((s) => s.repeat);
  const rate = usePlayerStore((s) => s.rate);
  const sleepAt = usePlayerStore((s) => s.sleepAt);
  const sleepEndOfTrack = usePlayerStore((s) => s.sleepEndOfTrack);

  const [scrub, setScrub] = useState(null);
  const [showLyrics, setShowLyrics] = useState(false);
  const [speedOpen, setSpeedOpen] = useState(false);
  const [sleepOpen, setSleepOpen] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [inPlaylist, setInPlaylist] = useState(false);
  const libraryTick = useLibraryStore((s) => s.tick);
  const menu = useTrackMenu();

  useEffect(() => {
    if (!track) router.back();
  }, [track, router]);

  useEffect(() => {
    let alive = true;
    if (track?.id) {
      isTrackInAnyPlaylist(track.id).then((v) => alive && setInPlaylist(v));
    } else {
      setInPlaylist(false);
    }
    return () => {
      alive = false;
    };
  }, [track?.id, libraryTick]);

  if (!track) return null;

  const sleepActive = sleepAt != null || sleepEndOfTrack;
  const sleepLabel = sleepEndOfTrack
    ? 'Stops at end of track'
    : sleepAt
      ? `Stops in ${Math.max(1, Math.round((sleepAt - Date.now()) / 60000))} min`
      : 'Off';
  const artSize = Math.min(width - 64, 360);
  const shown = scrub ?? currentTime;

  const ControlIcon = ({ onPress, children, hit = 10 }) => (
    <Pressable onPress={onPress} hitSlop={hit} style={({ pressed }) => ({ opacity: pressed ? 0.6 : 1, padding: 8 })}>
      {children}
    </Pressable>
  );

  return (
    <View style={{ flex: 1, backgroundColor: colors.background, paddingTop: insets.top + 8, paddingBottom: insets.bottom + 12 }}>
      {/* Header */}
      <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 12 }}>
        <ControlIcon onPress={() => router.back()}>
          <Ionicons name="chevron-down" size={26} color={colors.text} />
        </ControlIcon>
        <Text style={{ color: colors.textDim, fontSize: 12, fontWeight: '600', letterSpacing: 1 }}>NOW PLAYING</Text>
        <ControlIcon onPress={() => menu.open(track)}>
          <Ionicons name="ellipsis-vertical" size={20} color={colors.text} />
        </ControlIcon>
      </View>

      {/* Art / lyrics */}
      <View style={{ flex: 1, marginTop: 8 }}>
        {showLyrics ? (
          <LyricsView track={track} />
        ) : (
          <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center' }}>
            <TrackArt track={track} size={artSize} radius={12} iconSize={72} />
          </View>
        )}
      </View>

      {/* Title row */}
      <View style={{ flexDirection: 'row', alignItems: 'center', paddingHorizontal: 24, marginTop: 8 }}>
        <View style={{ flex: 1, marginRight: 12 }}>
          <Text numberOfLines={1} style={{ color: colors.text, fontSize: 20, fontWeight: '700' }}>{track.title}</Text>
          <Text numberOfLines={1} style={{ color: colors.textDim, fontSize: 14, marginTop: 2 }}>{track.artist}</Text>
        </View>
        <ControlIcon onPress={() => setPickerOpen(true)}>
          <Ionicons
            name={inPlaylist ? 'checkmark-circle' : 'add-circle-outline'}
            size={24}
            color={inPlaylist ? colors.accent : colors.text}
          />
        </ControlIcon>
      </View>

      {/* Seek bar */}
      <View style={{ paddingHorizontal: 16, marginTop: 4 }}>
        <Slider
          value={Math.min(shown, duration || 0)}
          minimumValue={0}
          maximumValue={Math.max(duration, 1)}
          onValueChange={setScrub}
          onSlidingComplete={(v) => {
            setScrub(null);
            seekTo(v);
          }}
          minimumTrackTintColor={colors.accent}
          maximumTrackTintColor={colors.surfaceHigh}
          thumbTintColor={colors.accent}
        />
        <View style={{ flexDirection: 'row', justifyContent: 'space-between', paddingHorizontal: 8 }}>
          <Text style={{ color: colors.textDim, fontSize: 12 }}>{formatTime(shown)}</Text>
          <Text style={{ color: colors.textDim, fontSize: 12 }}>-{formatTime(Math.max(0, (duration || 0) - shown))}</Text>
        </View>
      </View>

      {/* Main controls */}
      <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-evenly', marginTop: 4 }}>
        <ControlIcon onPress={toggleShuffle}>
          <Ionicons name="shuffle" size={24} color={shuffle ? colors.accent : colors.textDim} />
        </ControlIcon>
        <ControlIcon onPress={previous}>
          <Ionicons name="play-skip-back" size={32} color={colors.text} />
        </ControlIcon>
        <Pressable
          onPress={togglePlay}
          style={({ pressed }) => ({
            width: 68, height: 68, borderRadius: 34, backgroundColor: colors.text,
            alignItems: 'center', justifyContent: 'center', opacity: pressed ? 0.85 : 1,
          })}
        >
          <Ionicons name={isPlaying ? 'pause' : 'play'} size={32} color={colors.background} style={{ marginLeft: isPlaying ? 0 : 3 }} />
        </Pressable>
        <ControlIcon onPress={next}>
          <Ionicons name="play-skip-forward" size={32} color={colors.text} />
        </ControlIcon>
        <ControlIcon onPress={cycleRepeat}>
          <MaterialIcons
            name={repeat === 'one' ? 'repeat-one' : 'repeat'}
            size={24}
            color={repeat !== 'off' ? colors.accent : colors.textDim}
          />
        </ControlIcon>
      </View>

      {/* Secondary controls */}
      <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-evenly', marginTop: 10 }}>
        <ControlIcon onPress={() => setSpeedOpen(true)}>
          <Text style={{ color: rate !== 1 ? colors.accent : colors.textDim, fontSize: 13, fontWeight: '700' }}>
            {rate}x
          </Text>
        </ControlIcon>
        <ControlIcon onPress={() => setSleepOpen(true)}>
          <Ionicons name="moon-outline" size={20} color={sleepActive ? colors.accent : colors.textDim} />
        </ControlIcon>
        <ControlIcon onPress={() => setShowLyrics((v) => !v)}>
          <Ionicons name="text-outline" size={20} color={showLyrics ? colors.accent : colors.textDim} />
        </ControlIcon>
        <ControlIcon onPress={() => router.push('/queue')}>
          <Ionicons name="list-outline" size={22} color={colors.textDim} />
        </ControlIcon>
      </View>

      {/* Sheets */}
      <SheetMenu
        visible={speedOpen}
        onClose={() => setSpeedOpen(false)}
        title="Playback speed"
        items={RATES.map((r) => ({
          key: String(r),
          label: `${r}x${r === rate ? '   ✓' : ''}`,
          icon: 'speedometer-outline',
          onPress: () => setRate(r),
        }))}
      />
      <SheetMenu
        visible={sleepOpen}
        onClose={() => setSleepOpen(false)}
        title="Sleep timer"
        subtitle={sleepLabel}
        items={[
          ...[5, 15, 30, 60].map((m) => ({
            key: String(m),
            label: `${m} minutes`,
            icon: 'moon-outline',
            onPress: () => setSleepTimer(m),
          })),
          { key: 'end', label: 'End of track', icon: 'musical-note-outline', onPress: () => setSleepTimer('end') },
          sleepActive
            ? { key: 'off', label: 'Turn off timer', icon: 'close-circle-outline', destructive: true, onPress: clearSleepTimer }
            : null,
        ]}
      />
      <PlaylistPickerSheet visible={pickerOpen} trackIds={[track.id]} onClose={() => setPickerOpen(false)} />
      {menu.element}
    </View>
  );
}
