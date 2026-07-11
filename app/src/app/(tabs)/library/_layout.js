import { Stack } from 'expo-router';
import { useTheme } from '../../../theme/useTheme';

export default function LibraryLayout() {
  const colors = useTheme();
  return (
    <Stack
      screenOptions={{
        headerStyle: { backgroundColor: colors.background },
        headerTintColor: colors.text,
        headerTitleStyle: { color: colors.text },
        headerShadowVisible: false,
        contentStyle: { backgroundColor: colors.background },
      }}
    >
      <Stack.Screen name="index" options={{ headerShown: false }} />
      <Stack.Screen name="songs" options={{ title: 'Songs' }} />
      <Stack.Screen name="albums" options={{ title: 'Albums' }} />
      <Stack.Screen name="artists" options={{ title: 'Artists' }} />
      <Stack.Screen name="album/[key]" options={{ title: '' }} />
      <Stack.Screen name="artist/[name]" options={{ title: '' }} />
      <Stack.Screen name="playlist/[id]" options={{ title: '' }} />
    </Stack>
  );
}
