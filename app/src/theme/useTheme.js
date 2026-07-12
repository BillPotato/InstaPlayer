import { useColorScheme } from 'react-native';
import { useSettingsStore } from '../stores/settingsStore';
import { resolveColors } from './theme';

export function useTheme() {
  const mode = useSettingsStore((s) => s.themeMode);
  const accent = useSettingsStore((s) => s.accent);
  const scheme = useColorScheme();
  return resolveColors(mode, scheme, accent);
}
