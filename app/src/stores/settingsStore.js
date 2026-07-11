import { create } from 'zustand';
import * as SecureStore from 'expo-secure-store';
import { getSetting, setSetting } from '../db/settingsRepo';
import { DEFAULT_ACCENT } from '../theme/theme';

const KEY_SERVER_URL = 'server_url';
const KEY_API_KEY = 'api_key';

function normalizeUrl(url) {
  let u = (url || '').trim();
  if (!u) return '';
  if (!/^https?:\/\//i.test(u)) u = `http://${u}`;
  return u.replace(/\/+$/, '');
}

export const useSettingsStore = create((set) => ({
  hydrated: false,
  serverUrl: '',
  apiKey: '',
  setupDone: false,
  themeMode: 'system', // 'system' | 'dark' | 'light'
  accent: DEFAULT_ACCENT,

  hydrate: async () => {
    const [serverUrl, apiKey, setupDone, themeMode, accent] = await Promise.all([
      SecureStore.getItemAsync(KEY_SERVER_URL),
      SecureStore.getItemAsync(KEY_API_KEY),
      getSetting('setup_done', '0'),
      getSetting('theme_mode', 'system'),
      getSetting('accent', DEFAULT_ACCENT),
    ]);
    set({
      hydrated: true,
      serverUrl: serverUrl || '',
      apiKey: apiKey || '',
      setupDone: setupDone === '1',
      themeMode,
      accent,
    });
  },

  saveServer: async (url, key) => {
    const serverUrl = normalizeUrl(url);
    const apiKey = (key || '').trim();
    await SecureStore.setItemAsync(KEY_SERVER_URL, serverUrl);
    await SecureStore.setItemAsync(KEY_API_KEY, apiKey);
    await setSetting('setup_done', '1');
    set({ serverUrl, apiKey, setupDone: true });
  },

  skipSetup: async () => {
    await setSetting('setup_done', '1');
    set({ setupDone: true });
  },

  setThemeMode: async (themeMode) => {
    await setSetting('theme_mode', themeMode);
    set({ themeMode });
  },

  setAccent: async (accent) => {
    await setSetting('accent', accent);
    set({ accent });
  },
}));

export { normalizeUrl };
