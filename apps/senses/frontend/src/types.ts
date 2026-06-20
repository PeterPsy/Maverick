export interface SensesSettings {
  workspace_id: string;
  auth_mode: string;
  device_ingress_enabled: boolean;
  allow_member_pairing: boolean;
  require_admin_for_settings: boolean;
  pairing_code_ttl_seconds: number;
  max_frame_bytes: number;
  max_audio_bytes: number;
  jpeg_quality_hint: number;
  routing_followup_window_seconds: number;
  default_retention_class: string;
  failed_capture_ttl_seconds: number;
  created_at: string;
  updated_at: string;
}

export interface SensesDevice {
  workspace_id: string;
  device_id: string;
  owner_user_id: string;
  display_name: string;
  device_kind: string;
  platform: string;
  status: 'active' | 'revoked' | string;
  pairing_id: string | null;
  metadata: Record<string, unknown>;
  paired_at: string;
  last_seen_at: string | null;
  revoked_at: string | null;
  revoked_by_user_id: string | null;
  created_at: string;
  updated_at: string;
  can_revoke: boolean;
}

export interface SensesPairingSession {
  workspace_id: string;
  pairing_id: string;
  status: 'pending' | 'completed' | 'expired' | 'revoked' | string;
  created_by_user_id: string;
  completed_by_user_id: string | null;
  device_id: string | null;
  device_display_name: string | null;
  device_kind: string | null;
  platform: string | null;
  metadata: Record<string, unknown>;
  expires_at: string;
  created_at: string;
  completed_at: string | null;
  revoked_at: string | null;
  code?: string;
  qr_payload?: Record<string, unknown>;
  expires_in_seconds?: number;
}

export interface SensesActor {
  authenticated: boolean;
  user_id: string | null;
  workspace_role: string | null;
  platform_role: string | null;
  can_manage_workspace_devices: boolean;
}

export interface SensesOverview {
  ok: boolean;
  app_id: string;
  phase: string;
  workspace_id: string;
  actor: SensesActor;
  management: {
    can_manage_workspace_devices: boolean;
  };
  settings: SensesSettings;
  devices: SensesDevice[];
  pairing_sessions: SensesPairingSession[];
  dependencies: {
    status: string;
    blocked_reason?: string | null;
  };
}

export interface SensesActionResult {
  ok?: boolean;
  error?: string;
  detail?: string;
  overview?: SensesOverview;
  settings?: SensesSettings;
  device?: SensesDevice;
  devices?: SensesDevice[];
  pairing?: SensesPairingSession;
  pairing_sessions?: SensesPairingSession[];
}
