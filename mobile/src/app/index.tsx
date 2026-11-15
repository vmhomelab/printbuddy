import Ionicons from '@expo/vector-icons/Ionicons';
import { Stack, useRouter } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, FlatList, Pressable, RefreshControl, StyleSheet, Text, View } from 'react-native';

import { PrinterCard } from '@/components/PrinterCard.tsx';
import { ErrorText } from '@/components/ui.tsx';
import { errorMessage } from '@/lib/errors.ts';
import { t } from '@/lib/i18n.ts';
import { useLive } from '@/lib/live.tsx';
import { useApi } from '@/lib/session.tsx';
import { spacing, usePalette } from '@/lib/theme.ts';
import type { Printer } from '@/lib/types.ts';
import { useGuarded } from '@/lib/useGuarded.ts';

export default function PrintersScreen() {
  const api = useApi();
  const guarded = useGuarded();
  const router = useRouter();
  const p = usePalette();
  const { statuses, connected, setStatus } = useLive();
  const [printers, setPrinters] = useState<Printer[] | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const list = await guarded(() => api.printers());
      const active = list.filter((pr) => pr.is_active);
      setPrinters(active);
      // The WebSocket sends a snapshot on connect, but fetch once over REST too so
      // the list is filled even if the socket is blocked by a proxy.
      await Promise.all(
        active.map((pr) =>
          api
            .printerStatus(pr.id)
            .then((s) => setStatus(pr.id, s))
            .catch(() => undefined),
        ),
      );
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [api, guarded, setStatus]);

  useEffect(() => {
    void load();
  }, [load]);

  const onRefresh = async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  };

  return (
    <>
      <Stack.Screen
        options={{
          headerRight: () => (
            <Pressable accessibilityRole="button" accessibilityLabel={t.settings.title} onPress={() => router.push('/settings')} hitSlop={12}>
              <Ionicons name="settings-outline" size={24} color={p.accent} />
            </Pressable>
          ),
        }}
      />
      <FlatList
        contentInsetAdjustmentBehavior="automatic"
        style={{ backgroundColor: p.background }}
        contentContainerStyle={styles.list}
        data={printers ?? []}
        keyExtractor={(item) => String(item.id)}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={p.accent} />}
        ListHeaderComponent={
          <View style={styles.header}>
            <View style={[styles.liveDot, { backgroundColor: connected ? p.accent : p.warning }]} />
            <Text style={[styles.liveText, { color: p.textMuted }]}>{connected ? t.printers.live : t.printers.reconnecting}</Text>
          </View>
        }
        ListEmptyComponent={
          printers === null && !error ? (
            <ActivityIndicator color={p.accent} style={styles.empty} />
          ) : error ? (
            <ErrorText message={error} />
          ) : (
            <Text style={[styles.empty, { color: p.textMuted }]}>{t.printers.empty}</Text>
          )
        }
        renderItem={({ item }) => (
          <PrinterCard printer={item} status={statuses[item.id]} onPress={() => router.push(`/printers/${item.id}`)} />
        )}
      />
    </>
  );
}

const styles = StyleSheet.create({
  list: { padding: spacing.lg, gap: spacing.md },
  header: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  liveDot: { width: 8, height: 8, borderRadius: 4 },
  liveText: { fontSize: 13 },
  empty: { marginTop: spacing.xl, textAlign: 'center', fontSize: 15 },
});
