import type { MonitorPayload, MonitorState } from './types';

const BACKEND_URL = '/api/apps/maverick-monitor/backend';

async function post<T>(body: Record<string, unknown>): Promise<T> {
  const response = await fetch(BACKEND_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail || payload.error || 'Monitor request failed');
  }
  return payload as T;
}

export function loadSnapshot(): Promise<MonitorPayload> {
  return post<MonitorPayload>({ action: 'snapshot' });
}

export function updateSettings(settings: Partial<MonitorState>): Promise<{ state: MonitorState }> {
  return post<{ state: MonitorState }>({ action: 'settings.update', ...settings });
}
