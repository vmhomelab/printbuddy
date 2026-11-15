import { useColorScheme } from 'react-native';

import type { StateTone } from './format.ts';

/** Colors follow the web frontend (frontend/tailwind.config.js, "bambu" palette). */
const dark = {
  background: '#1a1a1a',
  card: '#2d2d2d',
  cardBorder: '#3d3d3d',
  text: '#f5f5f5',
  textMuted: '#a0a0a0',
  accent: '#00ae42',
  accentText: '#ffffff',
  danger: '#ef4444',
  warning: '#f59e0b',
  inputBackground: '#232323',
  track: '#3d3d3d',
};

const light: typeof dark = {
  background: '#f4f5f4',
  card: '#ffffff',
  cardBorder: '#e2e4e2',
  text: '#1a1a1a',
  textMuted: '#5f6360',
  accent: '#009438',
  accentText: '#ffffff',
  danger: '#dc2626',
  warning: '#b45309',
  inputBackground: '#ffffff',
  track: '#e2e4e2',
};

export type Palette = typeof dark;

export function usePalette(): Palette {
  return useColorScheme() === 'light' ? light : dark;
}

export function toneColor(tone: StateTone, p: Palette): string {
  switch (tone) {
    case 'active':
      return p.accent;
    case 'paused':
      return p.warning;
    case 'done':
      return '#3b82f6';
    case 'error':
      return p.danger;
    default:
      return p.textMuted;
  }
}

export const spacing = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24 } as const;
export const radius = { sm: 8, md: 12, lg: 16 } as const;
