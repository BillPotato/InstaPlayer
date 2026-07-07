import { View } from 'react-native';
import { Image } from 'expo-image';
import { Ionicons } from '@expo/vector-icons';
import { artUriForTrack } from '../downloads/paths';
import { useTheme } from '../theme/useTheme';

export function TrackArt({ track, uri, size = 48, radius = 4, iconSize }) {
  const colors = useTheme();
  const source = uri ?? (track ? artUriForTrack(track) : null);
  if (!source) {
    return (
      <View
        style={{
          width: size,
          height: size,
          borderRadius: radius,
          backgroundColor: colors.surfaceHigh,
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <Ionicons name="musical-notes" size={iconSize ?? size * 0.45} color={colors.textDim} />
      </View>
    );
  }
  return (
    <Image
      source={{ uri: source }}
      style={{ width: size, height: size, borderRadius: radius, backgroundColor: colors.surfaceHigh }}
      contentFit="cover"
      transition={100}
    />
  );
}
