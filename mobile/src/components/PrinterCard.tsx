import { Pressable, StyleSheet, Text, View } from 'react-native';

import { Card, ProgressBar, StateBadge } from '@/components/ui.tsx';
import {
  clampProgress,
  formatRemaining,
  formatTemp,
  isJobActive,
  jobName,
  stateKey,
  stateTone,
} from '@/lib/format.ts';
import { t } from '@/lib/i18n.ts';
import { spacing, toneColor, usePalette } from '@/lib/theme.ts';
import type { Printer, PrinterStatus } from '@/lib/types.ts';

export function PrinterCard({
  printer,
  status,
  onPress,
}: {
  printer: Printer;
  status: PrinterStatus | undefined;
  onPress: () => void;
}) {
  const p = usePalette();
  const key = stateKey(status);
  const active = isJobActive(key);
  const progress = clampProgress(status?.progress);
  const remaining = formatRemaining(status?.remaining_time);
  const temps = status?.temperatures;
  const nozzle = formatTemp(temps?.nozzle, temps?.nozzle_target);
  const bed = formatTemp(temps?.bed, temps?.bed_target);
  const alerts = status?.hms_errors?.length ?? 0;
  const name = jobName(status);

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`${printer.name}, ${t.states[key]}`}
      onPress={onPress}
      style={({ pressed }) => pressed && { opacity: 0.85 }}
    >
      <Card>
        <View style={styles.header}>
          <View style={styles.titleBlock}>
            <Text style={[styles.name, { color: p.text }]} numberOfLines={1}>
              {printer.name}
            </Text>
            {printer.model ? (
              <Text style={[styles.model, { color: p.textMuted }]} numberOfLines={1}>
                {printer.model}
              </Text>
            ) : null}
          </View>
          <StateBadge state={key} />
        </View>

        {active ? (
          <View style={styles.job}>
            {name ? (
              <Text style={[styles.jobName, { color: p.text }]} numberOfLines={1}>
                {name}
              </Text>
            ) : null}
            <ProgressBar value={progress} color={toneColor(stateTone(key), p)} />
            <View style={styles.row}>
              <Text style={[styles.meta, { color: p.text }]}>{Math.round(progress)} %</Text>
              {remaining ? (
                <Text style={[styles.meta, { color: p.textMuted }]}>
                  {remaining} {t.printers.remaining}
                </Text>
              ) : null}
            </View>
          </View>
        ) : null}

        {nozzle || bed || alerts > 0 ? (
          <View style={styles.row}>
            <View style={styles.temps}>
              {nozzle ? (
                <Text style={[styles.meta, { color: p.textMuted }]}>
                  {t.printers.nozzle} {nozzle}
                </Text>
              ) : null}
              {bed ? (
                <Text style={[styles.meta, { color: p.textMuted }]}>
                  {t.printers.bed} {bed}
                </Text>
              ) : null}
            </View>
            {alerts > 0 ? (
              <Text style={[styles.meta, { color: p.danger, fontWeight: '600' }]}>{t.printers.errorsCount(alerts)}</Text>
            ) : null}
          </View>
        ) : null}
      </Card>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  header: { flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', gap: spacing.md },
  titleBlock: { flex: 1, gap: 2 },
  name: { fontSize: 18, fontWeight: '700' },
  model: { fontSize: 13 },
  job: { gap: spacing.sm },
  jobName: { fontSize: 15, fontWeight: '500' },
  row: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: spacing.sm },
  temps: { flexDirection: 'row', gap: spacing.md },
  meta: { fontSize: 14, fontVariant: ['tabular-nums'] },
});
