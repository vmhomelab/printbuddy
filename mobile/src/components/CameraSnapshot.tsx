import { Image } from 'expo-image';
import { useIsFocused } from 'expo-router';
import { useEffect, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import type { PrintbuddyApi } from '@/lib/api.ts';
import { t } from '@/lib/i18n.ts';
import { radius, usePalette } from '@/lib/theme.ts';

const REFRESH_MS = 3_000;
const TOKEN_TTL_MS = 50 * 60_000; // server tokens live 60 minutes

/**
 * Polls /camera/snapshot every few seconds while the screen is focused.
 * A full MJPEG stream would need a native player; snapshots work on every provider.
 */
export function CameraSnapshot({ api, printerId, rotation = 0 }: { api: PrintbuddyApi; printerId: number; rotation?: number }) {
  const p = usePalette();
  const focused = useIsFocused();
  const [token, setToken] = useState<{ value: string | null; at: number } | null>(null);
  const [tick, setTick] = useState(() => Date.now());
  const [failed, setFailed] = useState(false);

  const tokenStale = !token || tick - token.at > TOKEN_TTL_MS;

  useEffect(() => {
    if (!focused || !tokenStale) return;
    let cancelled = false;
    api
      .cameraToken()
      .then((value) => {
        if (!cancelled) setToken({ value, at: Date.now() });
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [api, focused, tokenStale]);

  useEffect(() => {
    if (!focused) return;
    const timer = setInterval(() => setTick(Date.now()), REFRESH_MS);
    return () => clearInterval(timer);
  }, [focused]);

  const uri = token ? api.cameraSnapshotUrl(printerId, token.value, tick) : null;

  return (
    <View style={[styles.frame, { backgroundColor: p.inputBackground, borderColor: p.cardBorder }]}>
      {uri ? (
        <Image
          source={{ uri }}
          style={[styles.image, rotation ? { transform: [{ rotate: `${rotation}deg` }] } : null]}
          contentFit="contain"
          // keep showing the previous frame while the next one loads
          placeholder={null}
          transition={0}
          cachePolicy="none"
          onLoad={() => setFailed(false)}
          onError={() => setFailed(true)}
          accessibilityLabel={t.detail.camera}
        />
      ) : null}
      {failed || !uri ? (
        <View style={styles.overlay} pointerEvents="none">
          <Text style={{ color: p.textMuted }}>{t.detail.cameraUnavailable}</Text>
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  frame: {
    aspectRatio: 16 / 9,
    width: '100%',
    borderRadius: radius.md,
    borderWidth: StyleSheet.hairlineWidth,
    overflow: 'hidden',
  },
  image: { width: '100%', height: '100%' },
  overlay: { ...StyleSheet.absoluteFill, alignItems: 'center', justifyContent: 'center' },
});
