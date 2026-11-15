import { Platform } from 'react-native';
import * as SecureStore from 'expo-secure-store';

import type { Session } from './types.ts';

const SESSION_KEY = 'printbuddy.session.v1';

/**
 * Credentials live in the iOS Keychain / Android Keystore via expo-secure-store.
 * The web build (used for development only) falls back to localStorage.
 */
async function getRaw(): Promise<string | null> {
  if (Platform.OS === 'web') {
    try {
      return globalThis.localStorage?.getItem(SESSION_KEY) ?? null;
    } catch {
      return null;
    }
  }
  return SecureStore.getItemAsync(SESSION_KEY);
}

async function setRaw(value: string | null): Promise<void> {
  if (Platform.OS === 'web') {
    try {
      if (value === null) globalThis.localStorage?.removeItem(SESSION_KEY);
      else globalThis.localStorage?.setItem(SESSION_KEY, value);
    } catch {
      // storage unavailable (private mode) — session stays in memory only
    }
    return;
  }
  if (value === null) await SecureStore.deleteItemAsync(SESSION_KEY);
  else await SecureStore.setItemAsync(SESSION_KEY, value);
}

export async function loadSession(): Promise<Session | null> {
  const raw = await getRaw();
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Session;
    if (typeof parsed.serverUrl !== 'string' || !parsed.kind) return null;
    return parsed;
  } catch {
    return null;
  }
}

export async function saveSession(session: Session | null): Promise<void> {
  await setRaw(session ? JSON.stringify(session) : null);
}
