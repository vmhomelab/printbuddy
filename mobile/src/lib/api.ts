import type {
  AuthStatus,
  LoginResponse,
  Printer,
  PrinterStatus,
  Session,
  TwoFAMethod,
  UserInfo,
} from './types.ts';
import { apiUrl, withQuery } from './url.ts';

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string | null;

  constructor(status: number, detail: string | null) {
    super(detail ?? `HTTP ${status}`);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }

  get isUnauthorized(): boolean {
    return this.status === 401;
  }
}

/** Thrown when the server can't be reached at all (DNS, refused, timeout). */
export class NetworkError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'NetworkError';
  }
}

type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

const DEFAULT_TIMEOUT_MS = 15_000;

export function authHeaders(session: Pick<Session, 'kind' | 'token'>): Record<string, string> {
  if (!session.token || session.kind === 'none') return {};
  if (session.kind === 'apiKey') return { 'X-API-Key': session.token };
  return { Authorization: `Bearer ${session.token}` };
}

async function readDetail(res: Response): Promise<string | null> {
  try {
    const body: unknown = await res.json();
    if (body && typeof body === 'object' && 'detail' in body) {
      const detail = (body as { detail: unknown }).detail;
      if (typeof detail === 'string') return detail;
      if (Array.isArray(detail) && detail[0] && typeof detail[0].msg === 'string') return detail[0].msg;
    }
  } catch {
    // non-JSON error body
  }
  return null;
}

export class PrintbuddyApi {
  private readonly session: Session;
  private readonly fetchImpl: FetchLike;
  private readonly timeoutMs: number;

  constructor(session: Session, options: { fetch?: FetchLike; timeoutMs?: number } = {}) {
    this.session = session;
    this.fetchImpl = options.fetch ?? ((input, init) => fetch(input, init));
    this.timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  }

  async request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    const headers: Record<string, string> = { Accept: 'application/json', ...authHeaders(this.session) };
    if (body !== undefined) headers['Content-Type'] = 'application/json';

    let res: Response;
    try {
      res = await this.fetchImpl(apiUrl(this.session.serverUrl, path), {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
      });
    } catch (err) {
      throw new NetworkError(err instanceof Error ? err.message : String(err));
    } finally {
      clearTimeout(timer);
    }

    if (!res.ok) throw new ApiError(res.status, await readDetail(res));
    if (res.status === 204) return undefined as T;
    const text = await res.text();
    return (text ? JSON.parse(text) : undefined) as T;
  }

  authStatus(): Promise<AuthStatus> {
    return this.request('GET', '/auth/status');
  }

  login(username: string, password: string): Promise<LoginResponse> {
    return this.request('POST', '/auth/login', { username, password });
  }

  verify2fa(preAuthToken: string, code: string, method: TwoFAMethod): Promise<{ access_token: string; user: UserInfo }> {
    return this.request('POST', '/auth/2fa/verify', { pre_auth_token: preAuthToken, code, method });
  }

  sendEmailOtp(preAuthToken: string): Promise<unknown> {
    return this.request('POST', '/auth/2fa/email/send', { pre_auth_token: preAuthToken });
  }

  me(): Promise<UserInfo> {
    return this.request('GET', '/auth/me');
  }

  logout(): Promise<unknown> {
    return this.request('POST', '/auth/logout');
  }

  printers(): Promise<Printer[]> {
    return this.request('GET', '/printers/');
  }

  printer(id: number): Promise<Printer> {
    return this.request('GET', `/printers/${id}`);
  }

  printerStatus(id: number): Promise<PrinterStatus> {
    return this.request('GET', `/printers/${id}/status`);
  }

  pause(id: number): Promise<unknown> {
    return this.request('POST', `/printers/${id}/print/pause`);
  }

  resume(id: number): Promise<unknown> {
    return this.request('POST', `/printers/${id}/print/resume`);
  }

  stop(id: number): Promise<unknown> {
    return this.request('POST', `/printers/${id}/print/stop`);
  }

  /** Camera snapshot/stream URLs need a short-lived query token when auth is enabled. */
  async cameraToken(): Promise<string | null> {
    if (this.session.kind === 'none') return null;
    const res = await this.request<{ token: string }>('POST', '/printers/camera/stream-token');
    return res.token;
  }

  cameraSnapshotUrl(id: number, token: string | null, cacheBust: number): string {
    return withQuery(apiUrl(this.session.serverUrl, `/printers/${id}/camera/snapshot`), { t: cacheBust, token });
  }
}
