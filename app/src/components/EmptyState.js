import { Text, View, Pressable } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useTheme } from '../theme/useTheme';

export function EmptyState({
  icon = 'musical-notes', title, message,
  actionLabel, onAction,
  secondaryActionLabel, onSecondaryAction,
}) {
  const colors = useTheme();
  return (
    <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', padding: 32 }}>
      <Ionicons name={icon} size={48} color={colors.textDim} />
      <Text style={{ color: colors.text, fontSize: 18, fontWeight: '600', marginTop: 16, textAlign: 'center' }}>
        {title}
      </Text>
      {message ? (
        <Text style={{ color: colors.textDim, fontSize: 14, marginTop: 8, textAlign: 'center', lineHeight: 20 }}>
          {message}
        </Text>
      ) : null}
      {actionLabel ? (
        <Pressable
          onPress={onAction}
          style={({ pressed }) => ({
            backgroundColor: colors.accent,
            borderRadius: 24,
            paddingHorizontal: 24,
            paddingVertical: 12,
            marginTop: 20,
            opacity: pressed ? 0.8 : 1,
          })}
        >
          <Text style={{ color: colors.onAccent, fontWeight: '600' }}>{actionLabel}</Text>
        </Pressable>
      ) : null}
      {secondaryActionLabel ? (
        <Pressable
          onPress={onSecondaryAction}
          style={({ pressed }) => ({
            borderColor: colors.accent,
            borderWidth: 1,
            borderRadius: 24,
            paddingHorizontal: 24,
            paddingVertical: 12,
            marginTop: 12,
            opacity: pressed ? 0.8 : 1,
          })}
        >
          <Text style={{ color: colors.accent, fontWeight: '600' }}>{secondaryActionLabel}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}
