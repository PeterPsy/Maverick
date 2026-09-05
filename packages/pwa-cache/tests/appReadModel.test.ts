import { afterEach, expect, it, vi } from 'vitest';
import { readAppCacheModel } from '../src/appReadModel';
import { describeReadModelRequest } from '../src/readModelRequest';
import { readThroughParentDataCache } from '../src/dataCacheBrokerProtocol';
import { createReadModelRequestExecutor } from '../src';

vi.mock('../src/dataCacheBrokerProtocol', () => ({ readThroughParentDataCache: vi.fn() }));
afterEach(() => vi.restoreAllMocks());
const request = { appId: 'calendar', resource: 'bounded-event-window', schemaRevision: 'calendar.bounded-event-window.v1', parameters: { kind: 'window', offset: 0 } };
it('uses a stable opaque query identity and applies changed revalidation', async () => {
  const onRevalidated = vi.fn();
  vi.mocked(readThroughParentDataCache).mockResolvedValue({ payload: { value: 'old' }, revalidation: Promise.resolve({ changed: true, payload: { value: 'new' }, revision: 'new' }) } as never);
  await readAppCacheModel(request, (value) => value, { onRevalidated });
  await readAppCacheModel({ ...request, parameters: { offset: 0, kind: 'window' } }, (value) => value);
  const calls = vi.mocked(readThroughParentDataCache).mock.calls;
  expect(calls.at(-1)![0].entityId).toBe(calls.at(-2)![0].entityId);
  expect(calls.at(-1)![0].entityId).toMatch(/^[0-9a-f]{64}$/);
  expect(onRevalidated).toHaveBeenCalledWith({ value: 'new' });
});
it.each(['action', 'token', '_app_secret_request'])('does not grant extra request authority through %s', (key) => {
  expect(() => describeReadModelRequest({ ...request, parameters: { ...request.parameters, [key]: 'unsafe' } })).toThrow();
});
it('issues only the fixed Calendar read action', () => {
  const result = describeReadModelRequest(request);
  expect(result.endpoint).toBe('/api/apps/calendar/backend');
  expect(JSON.parse(result.body!)).toEqual({ kind: 'window', offset: 0, action: 'pwa.read_model', _app_secret_request: { logical_names: [], required: false } });
  expect(() => describeReadModelRequest({ ...request, parameters: { kind: 'delete' } })).toThrow();
});

it('issues pin discovery only as the non-mutating action, never list/repair or set', () => {
  const executor = createReadModelRequestExecutor({ appId: 'app-store', resource: 'pinned-apps' });
  expect(executor.endpoint).toBe('/api/apps/app-store/backend');
  expect(executor.method).toBe('POST');
  expect(JSON.parse(executor.body!)).toEqual({ action: 'pinned_apps.read' });
  for (const parameters of [{ action: 'pinned_apps.set' }, { app_ids: ['chat'] }, { endpoint: '/api/admin/users' }]) {
    expect(() => createReadModelRequestExecutor({ appId: 'app-store', resource: 'pinned-apps', parameters })).toThrow();
  }
});
