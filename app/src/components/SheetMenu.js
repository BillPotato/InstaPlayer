import { Modal, Pressable, Text, View, ScrollView } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useTheme } from '../theme/useTheme';

// Minimal bottom action sheet built on the core Modal — no extra deps.
// items: [{ key, label, icon, destructive, onPress }]
export function SheetMenu({ visible, onClose, title, subtitle, items }) {
  const colors = useTheme();
  const insets = useSafeAreaInsets();
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <Pressable style={{ flex: 1, backgroundColor: 'rgba(0,0,0,0.55)' }} onPress={onClose} />
      <View
        style={{
          backgroundColor: colors.surface,
          borderTopLeftRadius: 16,
          borderTopRightRadius: 16,
          paddingBottom: insets.bottom + 12,
          maxHeight: '70%',
        }}
      >
        {title ? (
          <View style={{ paddingHorizontal: 20, paddingTop: 16, paddingBottom: 8 }}>
            <Text numberOfLines={1} style={{ color: colors.text, fontSize: 16, fontWeight: '600' }}>
              {title}
            </Text>
            {subtitle ? (
              <Text numberOfLines={1} style={{ color: colors.textDim, fontSize: 13, marginTop: 2 }}>
                {subtitle}
              </Text>
            ) : null}
          </View>
        ) : null}
        <ScrollView bounces={false}>
          {items.filter(Boolean).map((item) => (
            <Pressable
              key={item.key}
              android_ripple={{ color: colors.surfaceHigh }}
              onPress={() => {
                onClose();
                // Let the sheet close before the action runs (some actions open
                // another modal, which Android won't stack).
                setTimeout(() => item.onPress?.(), 150);
              }}
              style={({ pressed }) => ({
                flexDirection: 'row',
                alignItems: 'center',
                paddingHorizontal: 20,
                paddingVertical: 14,
                opacity: pressed ? 0.7 : 1,
              })}
            >
              <Ionicons
                name={item.icon}
                size={20}
                color={item.destructive ? colors.danger : colors.text}
                style={{ marginRight: 16 }}
              />
              <Text style={{ color: item.destructive ? colors.danger : colors.text, fontSize: 15 }}>
                {item.label}
              </Text>
            </Pressable>
          ))}
        </ScrollView>
      </View>
    </Modal>
  );
}
