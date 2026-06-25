import type {
  SensesActionResult,
  SensesCaptureBundle,
  SensesDevice,
  SensesOverview,
  SensesPairingSession,
  SensesRoutingSession,
  SensesSettings,
} from './types';

export class SensesApiError extends Error {
  code: string;
  detail: string;
  status: number;

  constructor(code: string, detail: string, status: number) {
    super(detail || code || 'Senses request failed.');
    this.name = 'SensesApiError';
    this.code = code;
    this.detail = detail;
    this.status = status;
  }
}

async function request<T extends SensesActionResult>(body: Record<string, unknown>): Promise<T> {
  const response = await fetch('/api/apps/senses/backend', {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  const payload = (await response.json().catch(() => ({}))) as T;
  if (!response.ok || payload.ok === false || payload.error) {
    throw new SensesApiError(
      payload.error || 'senses_request_failed',
      payload.detail || payload.error || 'Senses request failed.',
      response.status,
    );
  }
  return payload;
}

export async function loadOverview(): Promise<SensesOverview> {
  const payload = await request<SensesOverview & SensesActionResult>({ action: 'overview' });
  return payload;
}

export async function loadViewFilter(): Promise<Record<string, unknown>> {
  const payload = await request<SensesActionResult & { state?: { view_filter?: Record<string, unknown> } }>({ action: 'view_filter' });
  return payload.state?.view_filter || {};
}

export async function setViewFilter(viewFilter: Record<string, unknown>): Promise<Record<string, unknown>> {
  const payload = await request<SensesActionResult & { state?: { view_filter?: Record<string, unknown> } }>({
    action: 'set_view_filter',
    view_filter: viewFilter,
  });
  return payload.state?.view_filter || {};
}

export async function startPairing(input: {
  deviceDisplayName?: string;
  deviceKind?: string;
  platform?: string;
} = {}): Promise<SensesPairingSession> {
  const payload = await request({
    action: 'pairing.start',
    device_display_name: input.deviceDisplayName || undefined,
    device_kind: input.deviceKind || 'ios',
    platform: input.platform || 'ios',
  });
  if (!payload.pairing) {
    throw new SensesApiError('invalid_pairing_response', 'Senses did not return a pairing session.', 500);
  }
  return payload.pairing;
}

export async function revokeDevice(deviceId: string): Promise<SensesDevice> {
  const payload = await request({ action: 'devices.revoke', device_id: deviceId });
  if (!payload.device) {
    throw new SensesApiError('invalid_device_response', 'Senses did not return the revoked device.', 500);
  }
  return payload.device;
}

export async function updateSettings(settings: Partial<SensesSettings>): Promise<SensesSettings> {
  const payload = await request({ action: 'settings.update', ...settings });
  if (!payload.settings) {
    throw new SensesApiError('invalid_settings_response', 'Senses did not return updated settings.', 500);
  }
  return payload.settings;
}

export async function resetRoutingSession(routingSessionId: string): Promise<SensesRoutingSession[]> {
  const payload = await request({ action: 'routing.reset', routing_session_id: routingSessionId });
  if (!payload.routing_sessions) {
    throw new SensesApiError('invalid_routing_response', 'Senses did not return routing sessions.', 500);
  }
  return payload.routing_sessions;
}

export async function startCaptureBundle(input: {
  bundleId: string;
  requestId: string;
}): Promise<SensesCaptureBundle> {
  const payload = await request({
    action: 'ingest.bundle.start',
    schema_version: 'senses.bundle.v1',
    bundle_id: input.bundleId,
    request_id: input.requestId,
    metadata: {
      origin_kind: 'meta_glasses',
      origin_label: 'Occhiali',
      source: 'senses.frontend.webkit_media_recorder',
    },
  });
  if (!payload.bundle) {
    throw new SensesApiError('invalid_bundle_response', 'Senses did not return a capture bundle.', 500);
  }
  return payload.bundle;
}

export async function ingestBundleAudioPart(input: {
  bundleId: string;
  requestId: string;
  idempotencyKey: string;
  contentBase64: string;
  contentType: string;
  durationSeconds: number;
  capturedAt: string;
  sizeBytes: number;
}): Promise<SensesCaptureBundle> {
  const payload = await request({
    action: 'ingest.bundle_part',
    bundle_id: input.bundleId,
    role: 'audio',
    schema_version: 'senses.audio.v1',
    request_id: input.requestId,
    idempotency_key: input.idempotencyKey,
    input_mode: 'audio.webkit_media_recorder',
    prompt: '',
    content_type: input.contentType,
    content_base64: input.contentBase64,
    duration_seconds: input.durationSeconds,
    captured_at: input.capturedAt,
    metadata: {
      origin_kind: 'meta_glasses',
      origin_label: 'Occhiali',
      source: 'senses.frontend.webkit_media_recorder',
      duration_seconds: input.durationSeconds,
      decoded_size_bytes: input.sizeBytes,
    },
  });
  if (!payload.bundle) {
    throw new SensesApiError('invalid_bundle_response', 'Senses did not return a capture bundle.', 500);
  }
  return payload.bundle;
}

export async function getCaptureBundle(bundleId: string): Promise<SensesCaptureBundle> {
  const payload = await request({ action: 'captures.bundle_get', bundle_id: bundleId });
  if (!payload.bundle) {
    throw new SensesApiError('invalid_bundle_response', 'Senses did not return a capture bundle.', 500);
  }
  return payload.bundle;
}

export async function dispatchCaptureBundle(bundleId: string): Promise<SensesActionResult> {
  const payload = await request({
    action: 'routing.dispatch_bundle',
    schema_version: 'senses.bundle.dispatch.v1',
    bundle_id: bundleId,
    agent_id: 'chat',
  });
  return payload;
}
