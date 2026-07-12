import { useEffect, useState } from 'react';
import { Text, View } from 'react-native';
import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import * as SplashScreen from 'expo-splash-screen';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { openDb } from '../db/db';
import { ensureDirs } from '../downloads/paths';
import { useSettingsStore } from '../stores/settingsStore';
import { initPlayer } from '../player/playerService';
import { initImportManager, resumePendingJobs } from '../downloads/importManager';
import { useTheme } from '../theme/useTheme';

SplashScreen.preventAutoHideAsync().catch(() => {});

export default function RootLayout() {
  const [ready, setReady] = useState(false);
  const [bootError, setBootError] = useState(null);
  const colors = useTheme();

  useEffect(() => {
    (async () => {
      try {
        await openDb();
        ensureDirs();
        await useSettingsStore.getState().hydrate();
        await initPlayer();
        initImportManager();
        // Recover interrupted imports in the background; never blocks boot.
        resumePendingJobs().catch(() => {});
      } catch (err) {
        setBootError(err);
      } finally {
        setReady(true);
        SplashScreen.hideAsync().catch(() => {});
      }
    })();
  }, []);

  if (!ready) return null;

  if (bootError) {
    return (
      <View style={{ flex: 1, backgroundColor: colors.background, alignItems: 'center', justifyContent: 'center', padding: 32 }}>
        <Text style={{ color: colors.text, fontSize: 18, fontWeight: '600' }}>Something went wrong</Text>
        <Text style={{ color: colors.textDim, marginTop: 8, textAlign: 'center' }}>{String(bootError?.message || bootError)}</Text>
      </View>
    );
  }

  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <StatusBar style={colors.dark ? 'light' : 'dark'} />
      <Stack
        screenOptions={{
          headerStyle: { backgroundColor: colors.background },
          headerTintColor: colors.text,
          headerTitleStyle: { color: colors.text },
          headerShadowVisible: false,
          contentStyle: { backgroundColor: colors.background },
        }}
      >
        <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
        <Stack.Screen name="setup" options={{ headerShown: false, animation: 'fade' }} />
        <Stack.Screen name="player" options={{ headerShown: false, presentation: 'modal', animation: 'slide_from_bottom' }} />
        <Stack.Screen name="queue" options={{ title: 'Queue', presentation: 'modal' }} />
        <Stack.Screen name="import" options={{ title: 'Add music', presentation: 'modal' }} />
        <Stack.Screen name="import-local" options={{ title: 'Import from device', presentation: 'modal' }} />
        <Stack.Screen name="settings/index" options={{ title: 'Settings' }} />
        <Stack.Screen name="settings/server" options={{ title: 'Server' }} />
        <Stack.Screen name="settings/appearance" options={{ title: 'Appearance' }} />
        <Stack.Screen name="settings/storage" options={{ title: 'Storage' }} />
        <Stack.Screen name="settings/about" options={{ title: 'About' }} />
      </Stack>
    </GestureHandlerRootView>
  );
}
