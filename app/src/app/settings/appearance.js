import { Pressable, ScrollView, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useTheme } from '../../theme/useTheme';
import { useSettingsStore } from '../../stores/settingsStore';
import { ACCENTS } from '../../theme/theme';

const MODES = [
  { key: 'system', label: 'Match system', icon: 'phone-portrait-outline' },
  { key: 'dark', label: 'Dark', icon: 'moon-outline' },
  { key: 'light', label: 'Light', icon: 'sunny-outline' },
];

export default function AppearanceScreen() {
  const colors = useTheme();
  const themeMode = useSettingsStore((s) => s.themeMode);
  const accent = useSettingsStore((s) => s.accent);
  const setThemeMode = useSettingsStore((s) => s.setThemeMode);
  const setAccent = useSettingsStore((s) => s.setAccent);

  return (
    <ScrollView style={{ flex: 1, backgroundColor: colors.background }} contentContainerStyle={{ padding: 20 }}>
      <Text style={{ color: colors.text, fontSize: 16, fontWeight: '700', marginBottom: 12 }}>Theme</Text>
      {MODES.map((m) => (
        <Pressable
          key={m.key}
          onPress={() => setThemeMode(m.key)}
          android_ripple={{ color: colors.surfaceHigh }}
          style={{ flexDirection: 'row', alignItems: 'center', paddingVertical: 12 }}
        >
          <Ionicons name={m.icon} size={20} color={colors.text} style={{ width: 32 }} />
          <Text style={{ color: colors.text, fontSize: 15, flex: 1 }}>{m.label}</Text>
          <Ionicons
            name={themeMode === m.key ? 'radio-button-on' : 'radio-button-off'}
            size={20}
            color={themeMode === m.key ? colors.accent : colors.textDim}
          />
        </Pressable>
      ))}

      <Text style={{ color: colors.text, fontSize: 16, fontWeight: '700', marginTop: 24, marginBottom: 16 }}>
        Accent color
      </Text>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 16 }}>
        {Object.entries(ACCENTS).map(([key, hex]) => (
          <Pressable
            key={key}
            onPress={() => setAccent(key)}
            style={{
              width: 48, height: 48, borderRadius: 24, backgroundColor: hex,
              alignItems: 'center', justifyContent: 'center',
              borderWidth: accent === key ? 3 : 0, borderColor: colors.text,
            }}
          >
            {accent === key ? <Ionicons name="checkmark" size={22} color="#fff" /> : null}
          </Pressable>
        ))}
      </View>
    </ScrollView>
  );
}
