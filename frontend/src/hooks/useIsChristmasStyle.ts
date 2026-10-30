import { useTheme } from '../contexts/ThemeContext';

/** True while the Christmas style is selected for the active light/dark mode. */
export function useIsChristmasStyle() {
  const { mode, darkStyle, lightStyle } = useTheme();
  return (mode === 'dark' ? darkStyle : lightStyle) === 'christmas';
}
