import { useState } from 'react';
import { Alert, Pressable, ScrollView, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useKeepAwake } from 'expo-keep-awake';
import { useRouter } from 'expo-router';
import { useTheme } from '../theme/useTheme';
import { useLocalImportStore } from '../stores/localImportStore';
import { useSettingsStore } from '../stores/settingsStore';
import { pickAndImportFiles, pickAndImportFolder } from '../localimport/localImportManager';

function Bar({ fraction, colors }) {
  return (
    <View style={{ height: 6, borderRadius: 3, backgroundColor: colors.surfaceHigh, overflow: 'hidden' }}>
      <View style={{ height: 6, width: `${Math.round(Math.min(1, Math.max(0, fraction)) * 100)}%`, backgroundColor: colors.accent }} />
    </View>
  );
}

function BigButton({ icon, label, sublabel, onPress, colors, disabled }) {
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled}
      style={({ pressed }) => ({
        backgroundColor: colors.surface,
        borderRadius: 12,
        padding: 18,
        flexDirection: 'row',
        alignItems: 'center',
        marginBottom: 12,
        opacity: disabled ? 0.5 : pressed ? 0.8 : 1,
      })}
    >
      <View
        style={{
          width: 48, height: 48, borderRadius: 12, backgroundColor: colors.surfaceHigh,
          alignItems: 'center', justifyContent: 'center',
        }}
      >
        <Ionicons name={icon} size={24} color={colors.accent} />
      </View>
      <View style={{ marginLeft: 14, flex: 1 }}>
        <Text style={{ color: colors.text, fontSize: 16, fontWeight: '600' }}>{label}</Text>
        <Text style={{ color: colors.textDim, fontSize: 13, marginTop: 2 }}>{sublabel}</Text>
      </View>
      <Ionicons name="chevron-forward" size={18} color={colors.textDim} />
    </Pressable>
  );
}

export default function ImportLocalScreen() {
  useKeepAwake();
  const colors = useTheme();
  const router = useRouter();
  const serverUrl = useSettingsStore((s) => s.serverUrl);
  const st = useLocalImportStore();
  const [busy, setBusy] = useState(false);

  const run = async (fn, emptyMessage) => {
    setBusy(true);
    try {
      const count = await fn();
      if (count === 0) {
        // User cancelled the picker or the folder had no audio — no state change.
      }
    } catch (err) {
      Alert.alert('Import failed', String(err?.message || err));
    } finally {
      setBusy(false);
    }
  };

  const runningNow = st.phase === 'running';

  return (
    <ScrollView style={{ flex: 1, backgroundColor: colors.background }} contentContainerStyle={{ padding: 20 }}>
      {!runningNow ? (
        <>
          <Text style={{ color: colors.textDim, fontSize: 13, lineHeight: 19, marginBottom: 16 }}>
            Import songs already on this device. Files are copied into InstaPlayer's own storage,
            so they keep playing even if the originals move or are deleted. Supported: FLAC, MP3,
            M4A/AAC, OGG/Opus, WAV.
          </Text>
          <BigButton
            icon="document-outline"
            label="Choose audio files"
            sublabel="Select one or more files"
            onPress={() => run(pickAndImportFiles)}
            colors={colors}
            disabled={busy}
          />
          <BigButton
            icon="folder-open-outline"
            label="Import a folder"
            sublabel="Scans the folder and its subfolders"
            onPress={() => run(pickAndImportFolder)}
            colors={colors}
            disabled={busy}
          />

          {st.phase === 'done' ? (
            <View style={{ marginTop: 12, backgroundColor: colors.surface, borderRadius: 10, padding: 16 }}>
              <View style={{ flexDirection: 'row', alignItems: 'center' }}>
                <Ionicons
                  name={st.failed > 0 ? 'alert-circle' : 'checkmark-circle'}
                  size={22}
                  color={st.failed > 0 ? colors.danger : colors.accent}
                />
                <Text style={{ color: colors.text, marginLeft: 10, fontWeight: '600' }}>
                  Imported {st.done} song{st.done === 1 ? '' : 's'}
                </Text>
              </View>
              {st.skipped > 0 ? (
                <Text style={{ color: colors.textDim, fontSize: 13, marginTop: 6 }}>
                  {st.skipped} skipped (already in your library).
                </Text>
              ) : null}
              {st.failed > 0 ? (
                <View style={{ marginTop: 6 }}>
                  <Text style={{ color: colors.danger, fontSize: 13 }}>{st.failed} failed:</Text>
                  {st.errors.map((e, i) => (
                    <Text key={i} numberOfLines={1} style={{ color: colors.textDim, fontSize: 12, marginTop: 2 }}>
                      {e.name} — {e.message}
                    </Text>
                  ))}
                </View>
              ) : null}
            </View>
          ) : null}

          {serverUrl ? (
            <Pressable
              onPress={() => router.replace('/import')}
              style={({ pressed }) => ({ alignItems: 'center', marginTop: 24, padding: 8, opacity: pressed ? 0.7 : 1 })}
            >
              <Text style={{ color: colors.accent, fontSize: 14, fontWeight: '600' }}>
                Add music from your server instead
              </Text>
            </Pressable>
          ) : null}
        </>
      ) : (
        <>
          <View style={{ flexDirection: 'row', alignItems: 'center', marginBottom: 16 }}>
            <Ionicons name="download-outline" size={22} color={colors.accent} />
            <Text style={{ color: colors.text, fontSize: 16, fontWeight: '700', marginLeft: 10 }}>
              Importing {st.done + st.failed + st.skipped}/{st.total}
            </Text>
          </View>
          <Bar fraction={st.total ? (st.done + st.failed + st.skipped) / st.total : 0} colors={colors} />
          {st.currentName ? (
            <Text numberOfLines={1} style={{ color: colors.textDim, fontSize: 13, marginTop: 10 }}>
              {st.currentName}
            </Text>
          ) : null}
          <Text style={{ color: colors.textDim, fontSize: 12, marginTop: 16 }}>
            Keep the app open until the import finishes.
          </Text>
        </>
      )}
    </ScrollView>
  );
}
