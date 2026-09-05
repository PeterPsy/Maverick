import { afterEach, expect, it, vi } from 'vitest';
import { readAppCacheModel } from '../src/appReadModel';
import { describeReadModelRequest } from '../src/readModelRequest';
import { readThroughParentDataCache } from '../src/dataCacheBrokerProtocol';

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
