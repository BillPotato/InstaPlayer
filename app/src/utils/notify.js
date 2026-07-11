import { Platform, ToastAndroid } from 'react-native';

// Lightweight, non-blocking feedback. No-op on iOS (no system toast; the
// actions this confirms are already visible in the UI there).
export function notify(message) {
  if (Platform.OS === 'android') ToastAndroid.show(message, ToastAndroid.SHORT);
}
