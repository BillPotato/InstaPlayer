import { Pressable, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useTheme } from '../theme/useTheme';
import { playContext, shufflePlay } from '../player/playerService';

export function PlayShuffleBar({ tracks }) {
  const colors = useTheme();
  if (!tracks.length) return null;
  return (
    <View style={{ flexDirection: 'row', gap: 12, paddingHorizontal: 16, paddingVertical: 12 }}>
      <Pressable
        onPress={() => playContext(tracks, 0, { shuffle: false })}
        style={({ pressed }) => ({
          flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
          backgroundColor: colors.accent, borderRadius: 24, paddingVertical: 12, opacity: pressed ? 0.85 : 1,
        })}
      >
        <Ionicons name="play" size={18} color={colors.onAccent} />
        <Text style={{ color: colors.onAccent, fontWeight: '700', marginLeft: 8 }}>Play</Text>
      </Pressable>
      <Pressable
        onPress={() => shufflePlay(tracks)}
        style={({ pressed }) => ({
          flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
          backgroundColor: colors.surfaceHigh, borderRadius: 24, paddingVertical: 12, opacity: pressed ? 0.85 : 1,
        })}
      >
        <Ionicons name="shuffle" size={18} color={colors.text} />
        <Text style={{ color: colors.text, fontWeight: '700', marginLeft: 8 }}>Shuffle</Text>
      </Pressable>
    </View>
  );
}
