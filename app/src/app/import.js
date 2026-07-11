import { useEffect, useState } from 'react';
import { ActivityIndicator, Alert, Pressable, ScrollView, Text, TextInput, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import * as Clipboard from 'expo-clipboard';
import { useKeepAwake } from 'expo-keep-awake';
import { useRouter } from 'expo-router';
import { useTheme } from '../theme/useTheme';
import { useImportStore } from '../stores/importStore';
import { useSettingsStore } from '../stores/settingsStore';
import { startImport, cancelImport } from '../downloads/importManager';
import { getDownloaderStatus, probeDownloader } from '../api/jobs';
import { HttpError } from '../api/client';
import { formatBytes } from '../utils/format';

// Availability card for the server's download engine. SpotiFLAC's upstream
// services break often, so surface state before the user pastes a link.
function DownloaderStatusCard({ colors }) {
  const [status, setStatus] = useState(null);
  const [hidden, setHidden] = useState(false);
  const [testing, setTesting] = useState(false);

  const refresh = async () => {
    try {
      setStatus(await getDownloaderStatus());
    } catch (err) {
      // Older backend without the endpoint — hide the card entirely.
      if (err instanceof HttpError && err.status === 404) setHidden(true);
    }
  };

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const runProbe = async () => {
    setTesting(true);
    try {
      // User explicitly asked for a test — always run a live one.
      await probeDownloader(true);
    } catch (err) {
      Alert.alert('Test failed to run', String(err?.message || err));
    } finally {
      setTesting(false);
      refresh();
    }
  };

  if (hidden || !status) return null;

  const probeAgeMin = status.lastProbe?.at
    ? Math.max(0, Math.round((Date.now() - Date.parse(status.lastProbe.at)) / 60000))
    : null;
  const probeStale = probeAgeMin == null || probeAgeMin > 90;
  let icon = 'checkmark-circle';
  let color = colors.accent;
  let headline = 'Download engine ready';
  let note = `Sources: ${status.services.join(', ')}${status.version ? ` · SpotiFLAC ${status.version}` : ''}`;
  if (!status.importable) {
    icon = 'close-circle';
    color = colors.danger;
    headline = 'Download engine unavailable on server';
    note = status.importError || 'SpotiFLAC could not be loaded.';
  } else if (status.lastProbe && !status.lastProbe.ok && !probeStale) {
    icon = 'warning';
    color = colors.danger;
    headline = 'Downloads may fail right now';
    note = status.lastProbe.detail || 'The last download test failed.';
  } else if (status.lastJob?.status === 'failed') {
    icon = 'warning';
    color = '#E5A50A';
    headline = 'Last server download failed';
    note = status.lastJob.error || 'The most recent job failed.';
  }

  return (
    <View style={{ backgroundColor: colors.surface, borderRadius: 10, padding: 14, marginBottom: 16 }}>
      <View style={{ flexDirection: 'row', alignItems: 'center' }}>
        <Ionicons name={icon} size={20} color={color} />
        <Text style={{ color: colors.text, fontWeight: '600', fontSize: 14, marginLeft: 8, flex: 1 }}>
          {headline}
        </Text>
      </View>
      <Text style={{ color: colors.textDim, fontSize: 12, marginTop: 6, lineHeight: 17 }}>{note}</Text>
      {status.lastProbe?.ok && !probeStale ? (
        <Text style={{ color: colors.textDim, fontSize: 12, marginTop: 4 }}>
          Download test passed{probeAgeMin != null ? ` ${probeAgeMin} min ago` : ''} (
          {Math.round(status.lastProbe.elapsedSeconds)}s).
        </Text>
      ) : null}
      {status.importable ? (
        <Pressable
          onPress={runProbe}
          disabled={testing || status.probing || status.activeJobs}
          style={({ pressed }) => ({
            flexDirection: 'row', alignItems: 'center', alignSelf: 'flex-start',
            marginTop: 10, opacity: testing || status.probing || status.activeJobs ? 0.5 : pressed ? 0.7 : 1,
          })}
        >
          {testing || status.probing ? (
            <ActivityIndicator size="small" color={colors.accent} />
          ) : (
            <Ionicons name="pulse-outline" size={16} color={colors.accent} />
          )}
          <Text style={{ color: colors.accent, fontSize: 13, fontWeight: '600', marginLeft: 6 }}>
            {testing || status.probing
              ? 'Testing — downloads one sample track, may take a couple of minutes…'
              : 'Test downloads now'}
          </Text>
        </Pressable>
      ) : null}
    </View>
  );
}

function Bar({ fraction, colors }) {
  return (
    <View style={{ height: 6, borderRadius: 3, backgroundColor: colors.surfaceHigh, overflow: 'hidden' }}>
      <View style={{ height: 6, width: `${Math.round(Math.min(1, Math.max(0, fraction)) * 100)}%`, backgroundColor: colors.accent }} />
    </View>
  );
}

export default function ImportScreen() {
  useKeepAwake();
  const colors = useTheme();
  const router = useRouter();
  const serverUrl = useSettingsStore((s) => s.serverUrl);
  const st = useImportStore();
  const [url, setUrl] = useState('');
  const [starting, setStarting] = useState(false);

  const running = ['creating', 'active', 'draining', 'cleanup'].includes(st.phase);

  const begin = async () => {
    const link = url.trim();
    if (!link) return;
    setStarting(true);
    try {
      await startImport(link);
      setUrl('');
    } catch (err) {
      Alert.alert('Could not start import', String(err?.message || err));
    } finally {
      setStarting(false);
    }
  };

  const paste = async () => {
    const text = await Clipboard.getStringAsync();
    if (text) setUrl(text.trim());
  };

  if (!serverUrl) {
    return (
      <View style={{ flex: 1, backgroundColor: colors.background, padding: 24, alignItems: 'center', justifyContent: 'center' }}>
        <Ionicons name="cloud-offline-outline" size={44} color={colors.textDim} />
        <Text style={{ color: colors.text, fontSize: 17, fontWeight: '600', marginTop: 12 }}>No server configured</Text>
        <Text style={{ color: colors.textDim, textAlign: 'center', marginTop: 8 }}>
          Set your server address and API key first.
        </Text>
        <Pressable
          onPress={() => router.push('/settings/server')}
          style={{ backgroundColor: colors.accent, borderRadius: 24, paddingHorizontal: 24, paddingVertical: 12, marginTop: 16 }}
        >
          <Text style={{ color: colors.onAccent, fontWeight: '600' }}>Open server settings</Text>
        </Pressable>
        <Pressable
          onPress={() => router.replace('/import-local')}
          style={{ borderColor: colors.accent, borderWidth: 1, borderRadius: 24, paddingHorizontal: 24, paddingVertical: 12, marginTop: 12 }}
        >
          <Text style={{ color: colors.accent, fontWeight: '600' }}>Import from this device</Text>
        </Pressable>
      </View>
    );
  }

  return (
    <ScrollView style={{ flex: 1, backgroundColor: colors.background }} contentContainerStyle={{ padding: 20 }}>
      {!running ? (
        <>
          <DownloaderStatusCard colors={colors} />
          <Text style={{ color: colors.text, fontSize: 15, fontWeight: '600', marginBottom: 8 }}>Paste a link</Text>
          <Text style={{ color: colors.textDim, fontSize: 13, lineHeight: 19, marginBottom: 12 }}>
            Paste a playlist, album or track link. Your server fetches the audio and this device
            downloads and stores it locally.
          </Text>
          <View style={{ flexDirection: 'row', alignItems: 'center', backgroundColor: colors.surfaceHigh, borderRadius: 10, paddingHorizontal: 12 }}>
            <TextInput
              value={url}
              onChangeText={setUrl}
              placeholder="https://…"
              placeholderTextColor={colors.textDim}
              autoCapitalize="none"
              autoCorrect={false}
              style={{ flex: 1, color: colors.text, paddingVertical: 12, fontSize: 14 }}
            />
            <Pressable onPress={paste} hitSlop={8} style={{ padding: 6 }}>
              <Ionicons name="clipboard-outline" size={18} color={colors.textDim} />
            </Pressable>
          </View>
          <Pressable
            onPress={begin}
            disabled={starting || !url.trim()}
            style={({ pressed }) => ({
              backgroundColor: colors.accent,
              opacity: starting || !url.trim() ? 0.5 : pressed ? 0.85 : 1,
              borderRadius: 24, paddingVertical: 14, alignItems: 'center', marginTop: 16,
            })}
          >
            <Text style={{ color: colors.onAccent, fontWeight: '700' }}>{starting ? 'Starting…' : 'Start import'}</Text>
          </Pressable>

          {st.phase === 'done' ? (
            <View style={{ marginTop: 24, backgroundColor: colors.surface, borderRadius: 10, padding: 16, flexDirection: 'row', alignItems: 'center' }}>
              <Ionicons name="checkmark-circle" size={22} color={colors.accent} />
              <Text style={{ color: colors.text, marginLeft: 10, flex: 1 }}>
                Imported {st.saved} song{st.saved === 1 ? '' : 's'}{st.name ? ` from “${st.name}”` : ''}.
              </Text>
            </View>
          ) : null}
          {st.phase === 'failed' ? (
            <View style={{ marginTop: 24, backgroundColor: colors.surface, borderRadius: 10, padding: 16 }}>
              <View style={{ flexDirection: 'row', alignItems: 'center' }}>
                <Ionicons name="alert-circle" size={22} color={colors.danger} />
                <Text style={{ color: colors.danger, marginLeft: 10, fontWeight: '600', flex: 1 }}>Last import failed</Text>
              </View>
              <Text style={{ color: colors.textDim, marginTop: 6, fontSize: 13 }}>{st.error}</Text>
              {st.saved > 0 ? (
                <Text style={{ color: colors.textDim, marginTop: 4, fontSize: 13 }}>
                  {st.saved} song{st.saved === 1 ? '' : 's'} were saved before it stopped.
                </Text>
              ) : null}
            </View>
          ) : null}

          <Pressable
            onPress={() => router.replace('/import-local')}
            style={({ pressed }) => ({ alignItems: 'center', marginTop: 24, padding: 8, opacity: pressed ? 0.7 : 1 })}
          >
            <Text style={{ color: colors.accent, fontSize: 14, fontWeight: '600' }}>
              Import files from this device instead
            </Text>
          </Pressable>
        </>
      ) : (
        <>
          <View style={{ flexDirection: 'row', alignItems: 'center' }}>
            <Ionicons name="cloud-download-outline" size={22} color={colors.accent} />
            <Text numberOfLines={1} style={{ color: colors.text, fontSize: 16, fontWeight: '700', marginLeft: 10, flex: 1 }}>
              {st.name || 'Importing…'}
            </Text>
          </View>

          <Text style={{ color: colors.textDim, fontSize: 13, marginTop: 16, marginBottom: 6 }}>
            Server progress {st.total ? `— ${st.backendCompleted}/${st.total}` : ''}
          </Text>
          <Bar fraction={st.total ? st.backendCompleted / st.total : 0} colors={colors} />
          {st.currentLabel ? (
            <Text numberOfLines={1} style={{ color: colors.textDim, fontSize: 12, marginTop: 6 }}>
              Fetching: {st.currentLabel}
            </Text>
          ) : null}

          <Text style={{ color: colors.textDim, fontSize: 13, marginTop: 18, marginBottom: 6 }}>
            Saved to this device {st.total ? `— ${st.saved}/${st.total}` : `— ${st.saved}`}
          </Text>
          <Bar fraction={st.total ? st.saved / st.total : 0} colors={colors} />
          {Object.entries(st.pulls).map(([n, pull]) => (
            <View key={n} style={{ marginTop: 10 }}>
              <Text numberOfLines={1} style={{ color: colors.text, fontSize: 13 }}>
                Downloading: {pull.title}
              </Text>
              <View style={{ marginTop: 4 }}>
                <Bar
                  fraction={pull.totalBytes > 0 ? pull.bytesWritten / pull.totalBytes : 0}
                  colors={colors}
                />
              </View>
              <Text style={{ color: colors.textDim, fontSize: 11, marginTop: 4 }}>
                {formatBytes(pull.bytesWritten)}
                {pull.totalBytes > 0 ? ` of ${formatBytes(pull.totalBytes)}` : ''}
              </Text>
            </View>
          ))}

          {st.failed > 0 ? (
            <Text style={{ color: colors.danger, fontSize: 13, marginTop: 12 }}>
              {st.failed} track{st.failed === 1 ? '' : 's'} failed to download.
            </Text>
          ) : null}

          <View style={{ flexDirection: 'row', alignItems: 'center', marginTop: 20, backgroundColor: colors.surface, borderRadius: 10, padding: 12 }}>
            <Ionicons name={st.connected ? 'wifi' : 'wifi-outline'} size={16} color={st.connected ? colors.accent : colors.danger} />
            <Text style={{ color: colors.textDim, fontSize: 12, marginLeft: 8, flex: 1 }}>
              {st.connected ? 'Connected to server.' : 'Reconnecting…'} Keep the app open while importing —
              the server stops a job if the app stays disconnected for more than a few seconds.
            </Text>
          </View>

          <Pressable
            onPress={() =>
              Alert.alert('Cancel import?', 'Songs already saved will stay in your library.', [
                { text: 'Keep importing', style: 'cancel' },
                { text: 'Cancel import', style: 'destructive', onPress: cancelImport },
              ])
            }
            style={({ pressed }) => ({
              borderColor: colors.danger, borderWidth: 1, borderRadius: 24,
              paddingVertical: 12, alignItems: 'center', marginTop: 20, opacity: pressed ? 0.7 : 1,
            })}
          >
            <Text style={{ color: colors.danger, fontWeight: '600' }}>Cancel import</Text>
          </Pressable>
        </>
      )}
    </ScrollView>
  );
}
