import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Alert, Pressable, ScrollView, Text, TextInput, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import * as Clipboard from 'expo-clipboard';
import { useKeepAwake } from 'expo-keep-awake';
import { useRouter } from 'expo-router';
import { useTheme } from '../theme/useTheme';
import { useImportStore } from '../stores/importStore';
import { useSettingsStore } from '../stores/settingsStore';
import { startImport, cancelImport } from '../downloads/importManager';
import { getDownloaderStatus } from '../api/jobs';
import { formatBytes } from '../utils/format';

// Availability card for the server's download engine. This is the ONLY way the
// app learns whether the backend is working — it renders the /downloader/status
// response passed down by the screen. There is no separate connection/probe
// test; the probe result shown here is the one the backend refreshes on its own
// schedule and reports in /status.
// Status light colours: green = ready, red = can't download (down/unreachable
// or downloads are currently failing).
const LIGHT_GREEN = '#22C55E';
const LIGHT_RED = '#EF4444';

// Single source of truth for the /status summary: the tiny light colour, a few
// plain words, and whether it's OK to start a download. `ready` is true only for
// the green state, so a red light both shows and blocks.
function serverStatus(status, statusState, colors) {
  const checking = statusState === 'loading' && !status;
  if (checking) {
    return { light: colors.textDim, label: 'Checking server…', ready: false, checking: true };
  }
  if (statusState === 'error' || !status) {
    return { light: LIGHT_RED, label: 'Can’t reach server', ready: false, checking: false };
  }
  const probeAgeMin = status.lastProbe?.at
    ? Math.max(0, Math.round((Date.now() - Date.parse(status.lastProbe.at)) / 60000))
    : null;
  const probeFresh = probeAgeMin != null && probeAgeMin <= 90;
  if (!status.importable) {
    return { light: LIGHT_RED, label: 'Downloads unavailable', ready: false, checking: false };
  }
  if (probeFresh && status.lastProbe && !status.lastProbe.ok) {
    return { light: LIGHT_RED, label: 'Downloads failing', ready: false, checking: false };
  }
  if (status.lastJob?.status === 'failed') {
    return { light: LIGHT_RED, label: 'Last download failed', ready: false, checking: false };
  }
  return { light: LIGHT_GREEN, label: 'Server ready', ready: true, checking: false };
}

// "Next check in ~X min" from the server's scheduled next probe (nextProbeAt).
// Null when there's no schedule (periodic probe off / hasn't run yet).
function nextProbeLabel(status) {
  const at = status?.nextProbeAt ? Date.parse(status.nextProbeAt) : NaN;
  if (Number.isNaN(at)) return null;
  const ms = at - Date.now();
  if (ms <= 0) return 'Next check due now';
  const min = Math.round(ms / 60000);
  return min < 1 ? 'Next check in under a minute' : `Next check in ~${min} min`;
}

function DownloaderStatusCard({ colors, status, statusState, onRetry }) {
  const { light, label, checking } = serverStatus(status, statusState, colors);
  const nextLabel = checking ? null : nextProbeLabel(status);

  return (
    <View
      style={{
        backgroundColor: colors.surface, borderRadius: 10, paddingVertical: 12,
        paddingHorizontal: 14, marginBottom: 16,
      }}
    >
      <View style={{ flexDirection: 'row', alignItems: 'center' }}>
        <View style={{ width: 11, height: 11, borderRadius: 6, backgroundColor: light }} />
        <Text style={{ color: colors.text, fontSize: 14, fontWeight: '600', marginLeft: 10, flex: 1 }}>
          {label}
        </Text>
        {checking ? (
          <ActivityIndicator size="small" color={colors.textDim} />
        ) : (
          <Pressable onPress={onRetry} hitSlop={8} style={({ pressed }) => ({ opacity: pressed ? 0.6 : 1, padding: 2 })}>
            <Ionicons name="refresh" size={16} color={colors.textDim} />
          </Pressable>
        )}
      </View>
      {nextLabel ? (
        <Text style={{ color: colors.textDim, fontSize: 12, marginTop: 4, marginLeft: 21 }}>
          {nextLabel}
        </Text>
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
  const quality = useSettingsStore((s) => s.quality);
  const setQuality = useSettingsStore((s) => s.setQuality);
  const st = useImportStore();
  const [url, setUrl] = useState('');
  const [starting, setStarting] = useState(false);
  const [status, setStatus] = useState(null);
  const [statusState, setStatusState] = useState('loading'); // loading | loaded | error

  const running = ['creating', 'active', 'draining', 'cleanup'].includes(st.phase);

  // The backend's health, straight from /downloader/status — the single gate on
  // whether we're allowed to send import requests.
  const refreshStatus = useCallback(async () => {
    setStatusState('loading');
    try {
      const s = await getDownloaderStatus();
      setStatus(s);
      setStatusState('loaded');
    } catch {
      setStatus(null);
      setStatusState('error');
    }
  }, []);

  useEffect(() => {
    if (serverUrl) refreshStatus();
  }, [serverUrl, refreshStatus]);

  // OK to import only when the status light is green (server responded, engine
  // available, and downloads aren't currently failing). Any red state blocks.
  const backendOk = serverStatus(status, statusState, colors).ready;

  const begin = async () => {
    const link = url.trim();
    if (!link) return;
    if (!backendOk) {
      Alert.alert(
        'Server not ready',
        'The backend isn’t reporting a healthy status right now. Check the download-engine status above and try again.',
      );
      return;
    }
    setStarting(true);
    try {
      await startImport(link, undefined, quality);
      setUrl('');
    } catch (err) {
      Alert.alert('Could not start import', String(err?.message || err));
    } finally {
      setStarting(false);
      // A job may have flipped activeJobs/lastJob — refresh the card.
      refreshStatus();
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
          <DownloaderStatusCard
            colors={colors}
            status={status}
            statusState={statusState}
            onRetry={refreshStatus}
          />
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

          <Text style={{ color: colors.textDim, fontSize: 13, marginTop: 16, marginBottom: 8 }}>Quality</Text>
          <View style={{ flexDirection: 'row', backgroundColor: colors.surfaceHigh, borderRadius: 10, padding: 4 }}>
            {[
              { value: 'LOSSLESS', label: 'Lossless', sub: '16-bit' },
              { value: 'HI_RES', label: 'Hi-Res', sub: '24-bit' },
            ].map((opt) => {
              const active = quality === opt.value;
              return (
                <Pressable
                  key={opt.value}
                  onPress={() => setQuality(opt.value)}
                  style={({ pressed }) => ({
                    flex: 1, paddingVertical: 8, borderRadius: 8, alignItems: 'center',
                    backgroundColor: active ? colors.accent : 'transparent',
                    opacity: pressed ? 0.85 : 1,
                  })}
                >
                  <Text style={{ color: active ? colors.onAccent : colors.text, fontSize: 13, fontWeight: '600' }}>
                    {opt.label}
                  </Text>
                  <Text style={{ color: active ? colors.onAccent : colors.textDim, fontSize: 11 }}>
                    {opt.sub}
                  </Text>
                </Pressable>
              );
            })}
          </View>
          <Text style={{ color: colors.textDim, fontSize: 11, marginTop: 6 }}>
            Hi-Res isn’t available for every track; the server falls back to the best it can get.
          </Text>

          <Pressable
            onPress={begin}
            disabled={starting || !url.trim() || !backendOk}
            style={({ pressed }) => ({
              backgroundColor: colors.accent,
              opacity: starting || !url.trim() || !backendOk ? 0.5 : pressed ? 0.85 : 1,
              borderRadius: 24, paddingVertical: 14, alignItems: 'center', marginTop: 16,
            })}
          >
            <Text style={{ color: colors.onAccent, fontWeight: '700' }}>{starting ? 'Starting…' : 'Start import'}</Text>
          </Pressable>
          {statusState !== 'loading' && !backendOk ? (
            <Text style={{ color: colors.textDim, fontSize: 12, marginTop: 8, textAlign: 'center' }}>
              Importing is disabled until the server reports it’s ready.
            </Text>
          ) : null}

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
