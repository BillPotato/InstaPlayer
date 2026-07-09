import { useState } from 'react';
import { ActivityIndicator, Platform, Pressable, Text, TextInput, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useTheme } from '../theme/useTheme';
import { useSettingsStore, normalizeUrl } from '../stores/settingsStore';
import { testConnection } from '../api/jobs';

// Shared server URL + API key form (first-run setup and settings).
export function ServerForm({ onSaved }) {
  const colors = useTheme();
  const serverUrl = useSettingsStore((s) => s.serverUrl);
  const apiKey = useSettingsStore((s) => s.apiKey);
  const saveServer = useSettingsStore((s) => s.saveServer);
  const [url, setUrl] = useState(serverUrl);
  const [key, setKey] = useState(apiKey);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null); // { ok, message }

  const inputStyle = {
    backgroundColor: colors.surfaceHigh,
    color: colors.text,
    borderRadius: 10,
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 14,
  };

  const test = async () => {
    setBusy(true);
    setResult(null);
    try {
      await testConnection(normalizeUrl(url), key.trim());
      setResult({ ok: true, message: 'Connected — server and API key look good.' });
      return true;
    } catch (err) {
      setResult({ ok: false, message: String(err?.message || err) });
      return false;
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    if (!url.trim()) return;
    setBusy(true);
    try {
      await saveServer(url, key);
      setResult({ ok: true, message: 'Saved.' });
      onSaved?.();
    } finally {
      setBusy(false);
    }
  };

  return (
    <View>
      <Text style={{ color: colors.textDim, fontSize: 13, marginBottom: 6 }}>Server address</Text>
      <TextInput
        value={url}
        onChangeText={setUrl}
        placeholder="http://192.168.1.10:8000"
        placeholderTextColor={colors.textDim}
        autoCapitalize="none"
        autoCorrect={false}
        keyboardType="url"
        style={inputStyle}
      />
      <Text style={{ color: colors.textDim, fontSize: 13, marginTop: 14, marginBottom: 6 }}>API key</Text>
      <TextInput
        value={key}
        onChangeText={setKey}
        placeholder="Your server's API key"
        placeholderTextColor={colors.textDim}
        autoCapitalize="none"
        autoCorrect={false}
        secureTextEntry
        style={inputStyle}
      />

      {Platform.OS === 'android' && /localhost|127\.0\.0\.1/i.test(url) ? (
        <View style={{ flexDirection: 'row', alignItems: 'flex-start', marginTop: 12 }}>
          <Ionicons name="information-circle" size={18} color={colors.accent} />
          <Text style={{ color: colors.textDim, fontSize: 13, marginLeft: 8, flex: 1, lineHeight: 18 }}>
            On Android, “localhost” is the phone itself. For a server on your computer use{' '}
            <Text style={{ color: colors.text }}>http://10.0.2.2:8000</Text> on an emulator, or your
            computer's LAN IP (like http://192.168.1.x:8000) on a real device.
          </Text>
        </View>
      ) : null}

      {result ? (
        <View style={{ flexDirection: 'row', alignItems: 'center', marginTop: 12 }}>
          <Ionicons
            name={result.ok ? 'checkmark-circle' : 'alert-circle'}
            size={18}
            color={result.ok ? colors.accent : colors.danger}
          />
          <Text style={{ color: result.ok ? colors.accent : colors.danger, fontSize: 13, marginLeft: 8, flex: 1 }}>
            {result.message}
          </Text>
        </View>
      ) : null}

      <View style={{ flexDirection: 'row', gap: 12, marginTop: 18 }}>
        <Pressable
          onPress={test}
          disabled={busy || !url.trim()}
          style={({ pressed }) => ({
            flex: 1, borderColor: colors.accent, borderWidth: 1, borderRadius: 24,
            paddingVertical: 12, alignItems: 'center',
            opacity: busy || !url.trim() ? 0.5 : pressed ? 0.8 : 1,
          })}
        >
          {busy ? <ActivityIndicator color={colors.accent} /> : <Text style={{ color: colors.accent, fontWeight: '600' }}>Test connection</Text>}
        </Pressable>
        <Pressable
          onPress={save}
          disabled={busy || !url.trim()}
          style={({ pressed }) => ({
            flex: 1, backgroundColor: colors.accent, borderRadius: 24,
            paddingVertical: 12, alignItems: 'center',
            opacity: busy || !url.trim() ? 0.5 : pressed ? 0.85 : 1,
          })}
        >
          <Text style={{ color: colors.onAccent, fontWeight: '700' }}>Save</Text>
        </Pressable>
      </View>
    </View>
  );
}
