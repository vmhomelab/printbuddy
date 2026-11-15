/**
 * Subset of the Printbuddy backend schemas the mobile app relies on.
 * Source of truth: backend/app/schemas/printer.py and backend/app/schemas/auth.py.
 */

/** How the app authenticates against the server. */
export type AuthKind = 'none' | 'jwt' | 'apiKey';

export interface Session {
  serverUrl: string;
  kind: AuthKind;
  /** JWT access token or API key; null when the server has auth disabled. */
  token: string | null;
  username?: string | null;
}

export interface AuthStatus {
  auth_enabled: boolean;
  requires_setup: boolean;
}

export interface UserInfo {
  id: number;
  username: string;
  is_admin: boolean;
  permissions: string[];
}

export interface LoginResponse {
  access_token: string | null;
  token_type: string;
  user: UserInfo | null;
  requires_2fa: boolean;
  pre_auth_token: string | null;
  two_fa_methods: string[];
}

export type TwoFAMethod = 'totp' | 'email' | 'backup';

export interface Printer {
  id: number;
  name: string;
  model?: string | null;
  provider?: string | null;
  location?: string | null;
  is_active: boolean;
  nozzle_count?: number;
  camera_rotation?: number;
}

export interface Temperatures {
  nozzle?: number;
  nozzle_target?: number;
  nozzle_2?: number;
  nozzle_2_target?: number;
  bed?: number;
  bed_target?: number;
  chamber?: number;
  chamber_target?: number;
  [key: string]: unknown;
}

export interface HMSError {
  code: string;
  attr?: number;
  module: number;
  /** 1=fatal, 2=serious, 3=common, 4=info */
  severity: number;
}

/** Live printer state as returned by GET /printers/{id}/status and the WebSocket. */
export interface PrinterStatus {
  id?: number;
  name?: string;
  connected: boolean;
  /** Bambu-style gcode_state: IDLE, PREPARE, RUNNING, PAUSE, FINISH, FAILED, ... */
  state: string | null;
  current_print?: string | null;
  subtask_name?: string | null;
  gcode_file?: string | null;
  /** 0–100 */
  progress?: number | null;
  /** Minutes */
  remaining_time?: number | null;
  layer_num?: number | null;
  total_layers?: number | null;
  temperatures?: Temperatures | null;
  hms_errors?: HMSError[];
  chamber_light?: boolean;
  chamber_light_supported?: boolean | null;
  door_open?: boolean;
  speed_level?: number;
  awaiting_plate_clear?: boolean;
  [key: string]: unknown;
}

/** Messages pushed by /api/v1/ws (backend/app/core/websocket.py). */
export type LiveMessage =
  | { type: 'printer_status'; printer_id: number; data: PrinterStatus }
  | { type: 'pong' }
  | { type: string; printer_id?: number; data?: unknown };
