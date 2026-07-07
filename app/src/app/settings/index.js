import { Pressable, ScrollView, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { useTheme } from '../../theme/useTheme';
import { useSettingsStore } from '../../stores/settingsStore';

function Row({ icon, label, sublabel, onPress, colors }) {
  return (
    <Pressable
      onPress={onPress}
      android_ripple={{ color: colors.surfaceHigh }}
      style={{ flexDirection: 'row', alignItems: 'center', paddingHorizontal: 20, paddingVertical: 14 }}
    >
      <Ionicons name={icon} size={22} color={colors.accent} style={{ width: 36 }} />
      <View style={{ flex: 1 }}>
        <Text style={{ color: colors.text, fontSize: 16 }}>{label}</Text>
        {sublabel ? <Text style={{ color: colors.textDim, fontSize: 13, marginTop: 2 }}>{sublabel}</Text> : null}
      </View>
      <Ionicons name="chevron-forward" size={18} color={colors.textDim} />
    </Pressable>
  );
}

export default function SettingsScreen() {
  const colors = useTheme();
  const router = useRouter();
  const serverUrl = useSettingsStore((s) => s.serverUrl);
  const themeMode = useSettingsStore((s) => s.themeMode);

  return (
    <ScrollView style={{ flex: 1, backgroundColor: colors.background }}>
      <Row
        icon="server-outline"
        label="Server"
        sublabel={serverUrl ? serverUrl.replace(/^https?:\/\//, '') : 'Not configured'}
        onPress={() => router.push('/settings/server')}
        colors={colors}
      />
      <Row
        icon="color-palette-outline"
        label="Appearance"
        sublabel={`Theme: ${themeMode[0].toUpperCase()}${themeMode.slice(1)}`}
        onPress={() => router.push('/settings/appearance')}
        colors={colors}
      />
      <Row icon="folder-open-outline" label="Storage" sublabel="Manage downloaded music" onPress={() => router.push('/settings/storage')} colors={colors} />
      <Row icon="information-circle-outline" label="About" onPress={() => router.push('/settings/about')} colors={colors} />
    </ScrollView>
  );
}
