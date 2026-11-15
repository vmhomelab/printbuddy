import { ApiError, NetworkError } from './api.ts';
import { t } from './i18n.ts';

export function errorMessage(err: unknown): string {
  if (err instanceof NetworkError) return t.errors.network;
  if (err instanceof ApiError) {
    if (err.status === 401) return t.errors.unauthorized;
    if (err.status === 403) return err.detail ?? t.errors.forbidden;
    return err.detail ?? t.errors.generic;
  }
  return t.errors.generic;
}
