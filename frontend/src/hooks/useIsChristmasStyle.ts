import { useTheme } from '../contexts/ThemeContext';

/** The Christmas variant selected for the active light/dark mode, if any. */
export function useChristmasVariant(): 'simple' | 'realistic' | null {
  const { mode, darkStyle, lightStyle } = useTheme();
  const style = mode === 'dark' ? darkStyle : lightStyle;
  if (style === 'christmas') return 'simple';
  if (style === 'christmas-realistic') return 'realistic';
  return null;
}

/** True while either Christmas style is selected for the active light/dark mode. */
export function useIsChristmasStyle() {
  return useChristmasVariant() !== null;
}
