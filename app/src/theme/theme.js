export const ACCENTS = {
  green: '#1DB954',
  blue: '#3D95F5',
  purple: '#9B6CF6',
  pink: '#F062A7',
  orange: '#F5842B',
  red: '#EF4B4B',
};

export const DEFAULT_ACCENT = 'green';

export const darkColors = {
  dark: true,
  background: '#121212',
  surface: '#1E1E1E',
  surfaceHigh: '#2A2A2A',
  text: '#FFFFFF',
  textDim: '#B3B3B3',
  border: '#2C2C2C',
  danger: '#F15E6C',
  onAccent: '#FFFFFF',
};

export const lightColors = {
  dark: false,
  background: '#FFFFFF',
  surface: '#F4F4F4',
  surfaceHigh: '#E9E9E9',
  text: '#121212',
  textDim: '#5E5E5E',
  border: '#DDDDDD',
  danger: '#C93A46',
  onAccent: '#FFFFFF',
};

export function resolveColors(mode, systemScheme, accentKey) {
  const dark = mode === 'system' ? systemScheme !== 'light' : mode === 'dark';
  const base = dark ? darkColors : lightColors;
  return { ...base, accent: ACCENTS[accentKey] || ACCENTS[DEFAULT_ACCENT] };
}
