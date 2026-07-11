import { useEffect, useState } from 'react';
import { KeyboardAvoidingView, Modal, Platform, Pressable, Text, TextInput, View } from 'react-native';
import { useTheme } from '../theme/useTheme';

export function InputDialog({ visible, title, placeholder, initialValue = '', submitLabel = 'Save', onSubmit, onClose }) {
  const colors = useTheme();
  const [value, setValue] = useState(initialValue);
  useEffect(() => {
    if (visible) setValue(initialValue);
  }, [visible, initialValue]);
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        style={{ flex: 1, backgroundColor: 'rgba(0,0,0,0.55)', justifyContent: 'center', padding: 32 }}
      >
        <View style={{ backgroundColor: colors.surface, borderRadius: 12, padding: 20 }}>
          <Text style={{ color: colors.text, fontSize: 17, fontWeight: '600', marginBottom: 12 }}>{title}</Text>
          <TextInput
            value={value}
            onChangeText={setValue}
            placeholder={placeholder}
            placeholderTextColor={colors.textDim}
            autoFocus
            style={{
              backgroundColor: colors.surfaceHigh,
              color: colors.text,
              borderRadius: 8,
              paddingHorizontal: 12,
              paddingVertical: 10,
              fontSize: 15,
            }}
          />
          <View style={{ flexDirection: 'row', justifyContent: 'flex-end', marginTop: 16 }}>
            <Pressable onPress={onClose} style={{ paddingVertical: 8, paddingHorizontal: 16 }}>
              <Text style={{ color: colors.textDim, fontWeight: '600' }}>Cancel</Text>
            </Pressable>
            <Pressable
              onPress={() => {
                const v = value.trim();
                if (!v) return;
                onClose();
                onSubmit(v);
              }}
              style={{ paddingVertical: 8, paddingHorizontal: 16 }}
            >
              <Text style={{ color: colors.accent, fontWeight: '600' }}>{submitLabel}</Text>
            </Pressable>
          </View>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}
