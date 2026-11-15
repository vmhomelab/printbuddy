import Constants from 'expo-constants';
import { useRouter } from 'expo-router';
import { ScrollView, StyleSheet, Text, View } from 'react-native';

import { Button, Card } from '@/components/ui.tsx';
import { t } from '@/lib/i18n.ts';
import { useSession } from '@/lib/session.tsx';
import { spacing, usePalette } from '@/lib/theme.ts';

export default function SettingsScreen() {
  const { session, signOut } = useSession();
  const router = useRouter();
  const p = usePalette();

  const authLabel =
    session?.kind === 'apiKey' ? t.settings.authApiKey : session?.kind === 'jwt' ? t.settings.authJwt : t.settings.authNone;

  const rows: { label: string; value: string }[] = [
    { label: t.settings.server, value: session?.serverUrl ?? '—' },
    { label: t.settings.authMethod, value: authLabel },
    ...(session?.username ? [{ label: t.settings.signedInAs, value: session.username }] : []),
    { label: t.settings.version, value: Constants.expoConfig?.version ?? '—' },
  ];

  return (
    <ScrollView style={{ backgroundColor: p.background }} contentContainerStyle={styles.content}>
      <Card>
        {rows.map((r) => (
          <View key={r.label} style={styles.row}>
            <Text style={[styles.label, { color: p.textMuted }]}>{r.label}</Text>
            <Text style={[styles.value, { color: p.text }]} selectable>
              {r.value}
            </Text>
          </View>
        ))}
      </Card>
      <Button
        label={t.settings.signOut}
        variant="danger"
        onPress={async () => {
          if (router.canDismiss()) router.dismissAll();
          await signOut();
        }}
      />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  content: { padding: spacing.lg, gap: spacing.lg },
  row: { gap: 2 },
  label: { fontSize: 13 },
  value: { fontSize: 16 },
});
