import { Pressable, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useTheme } from '../theme/useTheme';

// Header used inside tab screens (tabs render without native headers).
export function ScreenHeader({ title, right }) {
  const colors = useTheme();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  return (
    <View
      style={{
        paddingTop: insets.top + 8,
        paddingBottom: 12,
        paddingHorizontal: 16,
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
      }}
    >
      <Text style={{ color: colors.text, fontSize: 24, fontWeight: '700' }}>{title}</Text>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 4 }}>
        {right}
        <Pressable onPress={() => router.push('/settings')} hitSlop={8} style={{ padding: 6 }}>
          <Ionicons name="settings-outline" size={22} color={colors.text} />
        </Pressable>
      </View>
    </View>
  );
}
