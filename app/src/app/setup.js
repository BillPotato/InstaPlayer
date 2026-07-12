import { Pressable, ScrollView, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { ServerForm } from '../components/ServerForm';
import { useTheme } from '../theme/useTheme';
import { useSettingsStore } from '../stores/settingsStore';

export default function SetupScreen() {
  const colors = useTheme();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const skipSetup = useSettingsStore((s) => s.skipSetup);

  const done = () => router.replace('/');

  return (
    <ScrollView
      style={{ flex: 1, backgroundColor: colors.background }}
      contentContainerStyle={{ padding: 24, paddingTop: insets.top + 48, paddingBottom: insets.bottom + 24 }}
      keyboardShouldPersistTaps="handled"
    >
      <View style={{ alignItems: 'center', marginBottom: 32 }}>
        <View
          style={{
            width: 84, height: 84, borderRadius: 24, backgroundColor: colors.accent,
            alignItems: 'center', justifyContent: 'center',
          }}
        >
          <Ionicons name="musical-notes" size={44} color={colors.onAccent} />
        </View>
        <Text style={{ color: colors.text, fontSize: 26, fontWeight: '800', marginTop: 16 }}>InstaPlayer</Text>
        <Text style={{ color: colors.textDim, fontSize: 14, marginTop: 8, textAlign: 'center', lineHeight: 20 }}>
          Your music, on your device. Connect to your own server to add songs —
          everything is stored and played locally.
        </Text>
      </View>

      <ServerForm onSaved={done} />

      <Pressable onPress={async () => { await skipSetup(); done(); }} style={{ alignItems: 'center', marginTop: 24, padding: 8 }}>
        <Text style={{ color: colors.textDim, fontSize: 14 }}>Skip for now</Text>
      </Pressable>
      <Text style={{ color: colors.textDim, fontSize: 12, textAlign: 'center', marginTop: 4, lineHeight: 17 }}>
        No server? You can still import audio files already on this device from Library → +.
      </Text>
    </ScrollView>
  );
}
