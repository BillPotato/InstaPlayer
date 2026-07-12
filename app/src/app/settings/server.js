import { ScrollView, Text } from 'react-native';
import { ServerForm } from '../../components/ServerForm';
import { useTheme } from '../../theme/useTheme';

export default function ServerSettingsScreen() {
  const colors = useTheme();
  return (
    <ScrollView
      style={{ flex: 1, backgroundColor: colors.background }}
      contentContainerStyle={{ padding: 20 }}
      keyboardShouldPersistTaps="handled"
    >
      <Text style={{ color: colors.textDim, fontSize: 13, lineHeight: 19, marginBottom: 20 }}>
        InstaPlayer connects to a server you host yourself. Enter its address and API key.
        For access outside your home network, a VPN (such as Tailscale) or an HTTPS reverse
        proxy is recommended.
      </Text>
      <ServerForm />
    </ScrollView>
  );
}
