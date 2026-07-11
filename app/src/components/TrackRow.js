import { Pressable, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { TrackArt } from './TrackArt';
import { useTheme } from '../theme/useTheme';
import { useCurrentTrack, usePlayerStore } from '../player/playerStore';

export function TrackRow({ track, subtitle, onPress, onLongPress, onMenuPress, right, dimmed }) {
  const colors = useTheme();
  const current = useCurrentTrack();
  const isPlaying = usePlayerStore((s) => s.isPlaying);
  const isCurrent = current?.id === track.id;
  return (
    <Pressable
      onPress={onPress}
      onLongPress={onLongPress}
      android_ripple={{ color: colors.surfaceHigh }}
      style={({ pressed }) => ({
        flexDirection: 'row',
        alignItems: 'center',
        paddingHorizontal: 16,
        paddingVertical: 8,
        opacity: pressed || dimmed ? 0.7 : 1,
      })}
    >
      <TrackArt track={track} size={48} />
      <View style={{ flex: 1, marginLeft: 12, marginRight: 8 }}>
        <View style={{ flexDirection: 'row', alignItems: 'center' }}>
          {isCurrent ? (
            <Ionicons
              name={isPlaying ? 'volume-high' : 'volume-mute'}
              size={14}
              color={colors.accent}
              style={{ marginRight: 6 }}
            />
          ) : null}
          <Text
            numberOfLines={1}
            style={{
              color: isCurrent ? colors.accent : colors.text,
              fontSize: 16,
              fontWeight: '500',
              flexShrink: 1,
            }}
          >
            {track.title}
          </Text>
        </View>
        <Text numberOfLines={1} style={{ color: colors.textDim, fontSize: 13, marginTop: 2 }}>
          {subtitle ?? track.artist}
        </Text>
      </View>
      {right}
      {onMenuPress ? (
        <Pressable onPress={onMenuPress} hitSlop={12} style={{ padding: 4 }}>
          <Ionicons name="ellipsis-vertical" size={18} color={colors.textDim} />
        </Pressable>
      ) : null}
    </Pressable>
  );
}
