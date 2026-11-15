import { DarkTheme, DefaultTheme, SplashScreen, Stack, ThemeProvider } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useEffect } from 'react';
import { useColorScheme } from 'react-native';

import { t } from '@/lib/i18n.ts';
import { LiveStatusProvider } from '@/lib/live.tsx';
import { isAuthenticated, SessionProvider, useSession } from '@/lib/session.tsx';
import { usePalette } from '@/lib/theme.ts';

SplashScreen.preventAutoHideAsync().catch(() => undefined);

function RootStack() {
  const { ready, session } = useSession();
  const p = usePalette();
  const scheme = useColorScheme();

  useEffect(() => {
    if (ready) SplashScreen.hideAsync().catch(() => undefined);
  }, [ready]);

  if (!ready) return null;

  const authed = isAuthenticated(session);
  const base = scheme === 'light' ? DefaultTheme : DarkTheme;
  const theme = {
    ...base,
    colors: { ...base.colors, background: p.background, card: p.background, primary: p.accent, text: p.text, border: p.cardBorder },
  };

  return (
    <ThemeProvider value={theme}>
      <StatusBar style={scheme === 'light' ? 'dark' : 'light'} />
      <Stack screenOptions={{ headerTintColor: p.accent, headerTitleStyle: { color: p.text } }}>
        <Stack.Protected guard={authed}>
          <Stack.Screen name="index" options={{ title: t.printers.title, headerLargeTitle: true }} />
          <Stack.Screen name="printers/[id]" options={{ title: '' }} />
          <Stack.Screen name="settings" options={{ title: t.settings.title, presentation: 'modal' }} />
        </Stack.Protected>
        <Stack.Protected guard={!authed}>
          <Stack.Screen name="connect" options={{ headerShown: false }} />
        </Stack.Protected>
      </Stack>
    </ThemeProvider>
  );
}

export default function RootLayout() {
  return (
    <SessionProvider>
      <LiveStatusProvider>
        <RootStack />
      </LiveStatusProvider>
    </SessionProvider>
  );
}
