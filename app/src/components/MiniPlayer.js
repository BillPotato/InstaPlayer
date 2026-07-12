import { Pressable, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { TrackArt } from './TrackArt';
import { useTheme } from '../theme/useTheme';
import { useCurrentTrack, usePlayerStore } from '../player/playerStore';
import { togglePlay, next } from '../player/playerService';

export function MiniPlayer() {
  const colors = useTheme();
  const router = useRouter();
  const track = useCurrentTrack();
  const isPlaying = usePlayerStore((s) => s.isPlaying);
  const currentTime = usePlayerStore((s) => s.currentTime);
  const duration = usePlayerStore((s) => s.duration);
  if (!track) return null;
  const progress = duration > 0 ? Math.min(1, currentTime / duration) : 0;
  return (
    <Pressable
      onPress={() => router.push('/player')}
      style={{ backgroundColor: colors.surfaceHigh, marginHorizontal: 8, marginBottom: 4, borderRadius: 8, overflow: 'hidden' }}
    >
      <View style={{ flexDirection: 'row', alignItems: 'center', padding: 8 }}>
        <TrackArt track={track} size={40} />
        <View style={{ flex: 1, marginHorizontal: 10 }}>
          <Text numberOfLines={1} style={{ color: colors.text, fontSize: 14, fontWeight: '600' }}>
            {track.title}
          </Text>
          <Text numberOfLines={1} style={{ color: colors.textDim, fontSize: 12 }}>
            {track.artist}
          </Text>
        </View>
        <Pressable onPress={togglePlay} hitSlop={10} style={{ padding: 6 }}>
          <Ionicons name={isPlaying ? 'pause' : 'play'} size={24} color={colors.text} />
        </Pressable>
        <Pressable onPress={next} hitSlop={10} style={{ padding: 6 }}>
          <Ionicons name="play-skip-forward" size={20} color={colors.text} />
        </Pressable>
      </View>
      <View style={{ height: 2, backgroundColor: colors.border }}>
        <View style={{ height: 2, width: `${progress * 100}%`, backgroundColor: colors.accent }} />
      </View>
    </Pressable>
  );
}
