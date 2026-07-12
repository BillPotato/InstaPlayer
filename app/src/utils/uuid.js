import * as Crypto from 'expo-crypto';

export function randomId() {
  return Crypto.randomUUID().replace(/-/g, '');
}
