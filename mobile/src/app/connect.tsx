import { Image } from 'expo-image';
import { useState } from 'react';
import { KeyboardAvoidingView, Platform, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Button, Card, ErrorText, Field, Segmented } from '@/components/ui.tsx';
import { PrintbuddyApi } from '@/lib/api.ts';
import { errorMessage } from '@/lib/errors.ts';
import { t } from '@/lib/i18n.ts';
import { useSession } from '@/lib/session.tsx';
import { spacing, usePalette } from '@/lib/theme.ts';
import type { AuthStatus, Session, TwoFAMethod } from '@/lib/types.ts';
import { normalizeServerUrl } from '@/lib/url.ts';

type Step =
  | { kind: 'server' }
  | { kind: 'auth'; serverUrl: string; status: AuthStatus }
  | { kind: '2fa'; serverUrl: string; preAuthToken: string; methods: string[]; username: string };

type Method = 'login' | 'apiKey';

export default function ConnectScreen() {
  const p = usePalette();
  const { session, expired, signIn } = useSession();

  // After an expired session the server is already known: jump straight to sign-in.
  const [step, setStep] = useState<Step>(() =>
    session?.serverUrl
      ? { kind: 'auth', serverUrl: session.serverUrl, status: { auth_enabled: true, requires_setup: false } }
      : { kind: 'server' },
  );
  const [serverInput, setServerInput] = useState(session?.serverUrl ?? '');
  const [method, setMethod] = useState<Method>(session?.kind === 'apiKey' ? 'apiKey' : 'login');
  const [username, setUsername] = useState(session?.username ?? '');
  const [password, setPassword] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [code, setCode] = useState('');
  const [twoFaMethod, setTwoFaMethod] = useState<TwoFAMethod>('totp');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(expired ? t.errors.sessionExpired : null);

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const checkServer = () => {
    let serverUrl: string;
    try {
      serverUrl = normalizeServerUrl(serverInput);
    } catch {
      setError(t.errors.invalidUrl);
      return;
    }
    void run(async () => {
      const status = await new PrintbuddyApi({ serverUrl, kind: 'none', token: null }).authStatus();
      setServerInput(serverUrl);
      setStep({ kind: 'auth', serverUrl, status });
    });
  };

  const finish = (next: Session) => signIn(next);

  const connectWithoutAuth = (serverUrl: string) =>
    run(async () => {
      // Make sure the server really lets us in before storing the session.
      await new PrintbuddyApi({ serverUrl, kind: 'none', token: null }).printers();
      await finish({ serverUrl, kind: 'none', token: null });
    });

  const login = (serverUrl: string) =>
    run(async () => {
      const api = new PrintbuddyApi({ serverUrl, kind: 'none', token: null });
      const res = await api.login(username.trim(), password);
      if (res.requires_2fa && res.pre_auth_token) {
        const methods = res.two_fa_methods.length ? res.two_fa_methods : ['totp'];
        const first: TwoFAMethod = methods.includes('totp') ? 'totp' : 'email';
        if (first === 'email') await api.sendEmailOtp(res.pre_auth_token);
        setTwoFaMethod(first);
        setCode('');
        setStep({ kind: '2fa', serverUrl, preAuthToken: res.pre_auth_token, methods, username: username.trim() });
        return;
      }
      if (!res.access_token) throw new Error('no token');
      await finish({ serverUrl, kind: 'jwt', token: res.access_token, username: res.user?.username ?? username.trim() });
    });

  const loginWithApiKey = (serverUrl: string) =>
    run(async () => {
      const candidate: Session = { serverUrl, kind: 'apiKey', token: apiKey.trim() };
      await new PrintbuddyApi(candidate).printers();
      await finish(candidate);
    });

  const verify2fa = (s: Extract<Step, { kind: '2fa' }>) =>
    run(async () => {
      const api = new PrintbuddyApi({ serverUrl: s.serverUrl, kind: 'none', token: null });
      const res = await api.verify2fa(s.preAuthToken, code.trim(), twoFaMethod);
      await finish({ serverUrl: s.serverUrl, kind: 'jwt', token: res.access_token, username: res.user?.username ?? s.username });
    });

  const resetToServer = () => {
    setError(null);
    setStep({ kind: 'server' });
  };

  return (
    <SafeAreaView style={[styles.flex, { backgroundColor: p.background }]}>
      <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
          <View style={styles.hero}>
            <Image source={require('../../assets/splash-icon.png')} style={styles.logo} contentFit="contain" />
            <Text style={[styles.title, { color: p.text }]}>{t.connect.title}</Text>
            <Text style={[styles.subtitle, { color: p.textMuted }]}>{t.connect.subtitle}</Text>
          </View>

          {step.kind === 'server' ? (
            <Card>
              <Field
                label={t.connect.serverUrl}
                placeholder={t.connect.serverPlaceholder}
                value={serverInput}
                onChangeText={setServerInput}
                keyboardType="url"
                textContentType="URL"
                returnKeyType="go"
                onSubmitEditing={checkServer}
              />
              <ErrorText message={error} />
              <Button label={busy ? t.connect.checking : t.connect.check} onPress={checkServer} loading={busy} disabled={!serverInput.trim()} />
            </Card>
          ) : null}

          {step.kind === 'auth' ? (
            <Card>
              <Text style={[styles.server, { color: p.textMuted }]} numberOfLines={1}>
                {step.serverUrl}
              </Text>
              {step.status.requires_setup ? (
                <Text style={{ color: p.text }}>{t.connect.requiresSetup}</Text>
              ) : !step.status.auth_enabled ? (
                <>
                  <Text style={{ color: p.text }}>{t.connect.noAuth}</Text>
                  <ErrorText message={error} />
                  <Button label={t.connect.connectNoAuth} onPress={() => connectWithoutAuth(step.serverUrl)} loading={busy} />
                </>
              ) : (
                <>
                  <Segmented<Method>
                    value={method}
                    onChange={(m) => {
                      setMethod(m);
                      setError(null);
                    }}
                    options={[
                      { value: 'login', label: t.connect.methodLogin },
                      { value: 'apiKey', label: t.connect.methodApiKey },
                    ]}
                  />
                  {method === 'login' ? (
                    <>
                      <Field label={t.connect.username} value={username} onChangeText={setUsername} textContentType="username" autoComplete="username" />
                      <Field
                        label={t.connect.password}
                        value={password}
                        onChangeText={setPassword}
                        secureTextEntry
                        textContentType="password"
                        autoComplete="current-password"
                        returnKeyType="go"
                        onSubmitEditing={() => login(step.serverUrl)}
                      />
                      <ErrorText message={error} />
                      <Button
                        label={busy ? t.connect.signingIn : t.connect.signIn}
                        onPress={() => login(step.serverUrl)}
                        loading={busy}
                        disabled={!username.trim() || !password}
                      />
                    </>
                  ) : (
                    <>
                      <Field
                        label={t.connect.apiKey}
                        hint={t.connect.apiKeyHint}
                        value={apiKey}
                        onChangeText={setApiKey}
                        secureTextEntry
                        returnKeyType="go"
                        onSubmitEditing={() => loginWithApiKey(step.serverUrl)}
                      />
                      <ErrorText message={error} />
                      <Button label={t.connect.signIn} onPress={() => loginWithApiKey(step.serverUrl)} loading={busy} disabled={!apiKey.trim()} />
                    </>
                  )}
                </>
              )}
              <Button label={t.connect.changeServer} variant="secondary" onPress={resetToServer} disabled={busy} />
            </Card>
          ) : null}

          {step.kind === '2fa' ? (
            <Card>
              <Text style={[styles.cardTitle, { color: p.text }]}>{t.connect.twoFaTitle}</Text>
              <Field
                label={t.connect.twoFaCode}
                value={code}
                onChangeText={setCode}
                keyboardType={twoFaMethod === 'backup' ? 'default' : 'number-pad'}
                textContentType="oneTimeCode"
                autoComplete="one-time-code"
                autoCapitalize={twoFaMethod === 'backup' ? 'characters' : 'none'}
                maxLength={8}
                returnKeyType="go"
                onSubmitEditing={() => verify2fa(step)}
              />
              <ErrorText message={error} />
              <Button label={t.connect.verify} onPress={() => verify2fa(step)} loading={busy} disabled={code.trim().length < 6} />
              <Button
                variant="secondary"
                label={twoFaMethod === 'backup' ? t.connect.twoFaTotp : t.connect.twoFaBackup}
                onPress={() => {
                  setCode('');
                  setTwoFaMethod(twoFaMethod === 'backup' ? (step.methods.includes('totp') ? 'totp' : 'email') : 'backup');
                }}
                disabled={busy}
              />
              <Button label={t.connect.changeServer} variant="secondary" onPress={resetToServer} disabled={busy} />
            </Card>
          ) : null}
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  content: { padding: spacing.lg, gap: spacing.xl, flexGrow: 1, justifyContent: 'center', maxWidth: 480, width: '100%', alignSelf: 'center' },
  hero: { alignItems: 'center', gap: spacing.sm },
  logo: { width: 96, height: 96 },
  title: { fontSize: 24, fontWeight: '700', textAlign: 'center' },
  subtitle: { fontSize: 15, textAlign: 'center' },
  server: { fontSize: 13 },
  cardTitle: { fontSize: 18, fontWeight: '700' },
});
