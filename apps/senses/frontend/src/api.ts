import type { SensesActionResult, SensesDevice, SensesOverview, SensesPairingSession } from './types';

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
