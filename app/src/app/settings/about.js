import { ScrollView, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import Constants from 'expo-constants';
import { useTheme } from '../../theme/useTheme';

export default function AboutScreen() {
  const colors = useTheme();
  const version = Constants.expoConfig?.version ?? '1.0.0';
  return (
    <ScrollView style={{ flex: 1, backgroundColor: colors.background }} contentContainerStyle={{ padding: 24 }}>
      <View style={{ alignItems: 'center', marginBottom: 24 }}>
        <View
          style={{
            width: 72, height: 72, borderRadius: 20, backgroundColor: colors.accent,
            alignItems: 'center', justifyContent: 'center',
          }}
        >
          <Ionicons name="musical-notes" size={38} color={colors.onAccent} />
        </View>
        <Text style={{ color: colors.text, fontSize: 20, fontWeight: '800', marginTop: 12 }}>InstaPlayer</Text>
        <Text style={{ color: colors.textDim, fontSize: 13, marginTop: 4 }}>Version {version}</Text>
      </View>

      <Text style={{ color: colors.text, fontSize: 15, fontWeight: '700', marginBottom: 6 }}>What is this?</Text>
      <Text style={{ color: colors.textDim, fontSize: 14, lineHeight: 21, marginBottom: 18 }}>
        InstaPlayer is an offline-first music player for your own, self-hosted music server.
        Songs are downloaded to this device and play without an internet connection.
      </Text>

      <Text style={{ color: colors.text, fontSize: 15, fontWeight: '700', marginBottom: 6 }}>Privacy</Text>
      <Text style={{ color: colors.textDim, fontSize: 14, lineHeight: 21, marginBottom: 18 }}>
        InstaPlayer collects no data. Your music, playlists, listening history and settings never
        leave this device, except for requests made to the server address you configure yourself.
      </Text>

      <Text style={{ color: colors.text, fontSize: 15, fontWeight: '700', marginBottom: 6 }}>Security note</Text>
      <Text style={{ color: colors.textDim, fontSize: 14, lineHeight: 21 }}>
        Your server's API key is stored in this device's secure keystore. If you access your server
        over the internet, prefer a VPN (such as Tailscale) or an HTTPS reverse proxy rather than
        exposing it directly.
      </Text>
    </ScrollView>
  );
}
