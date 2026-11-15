import { Stack, useLocalSearchParams } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import { RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';

import { CameraSnapshot } from '@/components/CameraSnapshot.tsx';
import { Button, Card, ErrorText, ProgressBar, SectionTitle, StateBadge } from '@/components/ui.tsx';
import { confirmDestructive } from '@/lib/confirm.ts';
import { errorMessage } from '@/lib/errors.ts';
import {
  clampProgress,
  formatEta,
  formatRemaining,
  formatTemp,
  isJobActive,
  jobName,
  stateKey,
  stateTone,
} from '@/lib/format.ts';
import { locale, t } from '@/lib/i18n.ts';
import { useLive } from '@/lib/live.tsx';
import { useApi } from '@/lib/session.tsx';
import { spacing, toneColor, usePalette } from '@/lib/theme.ts';
import type { Printer } from '@/lib/types.ts';
import { useGuarded } from '@/lib/useGuarded.ts';

type Action = 'pause' | 'resume' | 'stop';

export default function PrinterDetailScreen() {
  const { id: idParam } = useLocalSearchParams<{ id: string }>();
  const id = Number(idParam);
  const api = useApi();
  const guarded = useGuarded();
  const p = usePalette();
  const { statuses, setStatus } = useLive();
  const status = statuses[id];

  const [printer, setPrinter] = useState<Printer | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [pending, setPending] = useState<Action | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [pr, st] = await Promise.all([guarded(() => api.printer(id)), guarded(() => api.printerStatus(id))]);
      setPrinter(pr);
      setStatus(id, st);
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [api, guarded, id, setStatus]);

  useEffect(() => {
    void load();
  }, [load]);

  const act = async (action: Action) => {
    if (action === 'stop') {
      const ok = await confirmDestructive(t.detail.stopConfirmTitle, t.detail.stopConfirmBody, t.detail.stop, t.detail.cancel);
      if (!ok) return;
    }
    setPending(action);
    setError(null);
    try {
      await guarded(() => api[action](id));
      // The WebSocket will push the new state; refresh explicitly in case it is slow.
      setStatus(id, await api.printerStatus(id));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setPending(null);
    }
  };

  const key = stateKey(status);
  const active = isJobActive(key);
  const progress = clampProgress(status?.progress);
  const remaining = formatRemaining(status?.remaining_time);
  const eta = formatEta(status?.remaining_time, new Date(), locale);
  const temps = status?.temperatures;
  const name = jobName(status);
  const tempRows = [
    { label: t.printers.nozzle, value: formatTemp(temps?.nozzle, temps?.nozzle_target) },
    { label: `${t.printers.nozzle} 2`, value: formatTemp(temps?.nozzle_2, temps?.nozzle_2_target) },
    { label: t.printers.bed, value: formatTemp(temps?.bed, temps?.bed_target) },
    { label: t.printers.chamber, value: formatTemp(temps?.chamber, temps?.chamber_target) },
  ].filter((r): r is { label: string; value: string } => r.value !== null);
  const alerts = status?.hms_errors?.length ?? 0;

  return (
    <>
      <Stack.Screen options={{ title: printer?.name ?? status?.name ?? '' }} />
      <ScrollView
        contentInsetAdjustmentBehavior="automatic"
        style={{ backgroundColor: p.background }}
        contentContainerStyle={styles.content}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            tintColor={p.accent}
            onRefresh={async () => {
              setRefreshing(true);
              await load();
              setRefreshing(false);
            }}
          />
        }
      >
        <View style={styles.badgeRow}>
          <StateBadge state={key} />
          {printer?.model ? <Text style={{ color: p.textMuted }}>{printer.model}</Text> : null}
        </View>

        {status?.connected ? <CameraSnapshot api={api} printerId={id} rotation={printer?.camera_rotation ?? 0} /> : null}

        {alerts > 0 || status?.door_open || status?.awaiting_plate_clear ? (
          <Card style={{ borderColor: p.warning }}>
            {alerts > 0 ? <Text style={{ color: p.danger, fontWeight: '600' }}>{t.printers.errorsCount(alerts)}</Text> : null}
            {status?.door_open ? <Text style={{ color: p.warning }}>{t.detail.doorOpen}</Text> : null}
            {status?.awaiting_plate_clear ? <Text style={{ color: p.warning }}>{t.detail.plateClear}</Text> : null}
          </Card>
        ) : null}

        <Card>
          <SectionTitle>{t.detail.job}</SectionTitle>
          {active ? (
            <>
              {name ? (
                <Text style={[styles.jobName, { color: p.text }]} numberOfLines={2}>
                  {name}
                </Text>
              ) : null}
              <ProgressBar value={progress} color={toneColor(stateTone(key), p)} />
              <View style={styles.statsRow}>
                <Stat label={t.printers.progress} value={`${Math.round(progress)} %`} />
                {remaining ? <Stat label={t.printers.remaining} value={remaining} /> : null}
                {eta ? <Stat label={t.printers.eta} value={eta} /> : null}
                {status?.total_layers ? (
                  <Stat label={t.printers.layer} value={`${status.layer_num ?? 0} / ${status.total_layers}`} />
                ) : null}
              </View>
              <View style={styles.actions}>
                {key === 'paused' ? (
                  <Button label={t.detail.resume} onPress={() => act('resume')} loading={pending === 'resume'} disabled={pending !== null} style={styles.flex} />
                ) : (
                  <Button
                    label={t.detail.pause}
                    variant="secondary"
                    onPress={() => act('pause')}
                    loading={pending === 'pause'}
                    disabled={pending !== null || key !== 'printing'}
                    style={styles.flex}
                  />
                )}
                <Button label={t.detail.stop} variant="danger" onPress={() => act('stop')} loading={pending === 'stop'} disabled={pending !== null} style={styles.flex} />
              </View>
            </>
          ) : (
            <Text style={{ color: p.textMuted }}>{t.detail.noJob}</Text>
          )}
          <ErrorText message={error} />
        </Card>

        {tempRows.length > 0 ? (
          <Card>
            <SectionTitle>{t.detail.temperatures}</SectionTitle>
            <View style={styles.statsRow}>
              {tempRows.map((r) => (
                <Stat key={r.label} label={r.label} value={r.value} />
              ))}
            </View>
          </Card>
        ) : null}
      </ScrollView>
    </>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  const p = usePalette();
  return (
    <View style={styles.stat}>
      <Text style={[styles.statValue, { color: p.text }]}>{value}</Text>
      <Text style={[styles.statLabel, { color: p.textMuted }]}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  content: { padding: spacing.lg, gap: spacing.lg },
  badgeRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  jobName: { fontSize: 17, fontWeight: '600' },
  statsRow: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xl, rowGap: spacing.md },
  stat: { gap: 2 },
  statValue: { fontSize: 18, fontWeight: '700', fontVariant: ['tabular-nums'] },
  statLabel: { fontSize: 12 },
  actions: { flexDirection: 'row', gap: spacing.md },
  flex: { flex: 1 },
});
