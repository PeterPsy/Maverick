import { afterEach, expect, it, vi } from 'vitest';
import { registerMaverickAppHibernation, preventMaverickAppHibernation, MAX_APP_SNAPSHOT_BYTES } from '../src/appHibernation';

afterEach(() => vi.unstubAllGlobals());

it('captures only hidden, unblocked apps from the exact parent and restores once', async () => {
  const parent = { postMessage: vi.fn() };
  const target = Object.assign(new EventTarget(), { parent, location: { origin: 'https://frame.test' },
    __MAVERICK_PLATFORM_ORIGIN__: 'https://shell.test' });
  vi.stubGlobal('window', target);
  vi.stubGlobal('document', Object.assign(new EventTarget(), { hidden: false }));
  vi.stubGlobal('navigator', { onLine: true });
  const snapshot = { params: { thread_id: 'thread-a' }, state: { draft: 'unsent' } };
  const capture = vi.fn(() => snapshot);
  const media: Array<{ paused: boolean; currentTime: number }> = [];
  Object.assign(document, { querySelectorAll: () => media });
  const restore = vi.fn();
  const dispose = registerMaverickAppHibernation({ appId: 'chat', capture, restore });
  const message = (data: object, source = parent, origin = 'https://shell.test') => target.dispatchEvent(Object.assign(new Event('message'), {
    data, origin, source,
  }));
  const request = { type: 'maverick.app.hibernate', app_id: 'chat', request_id: 'one' };
  try {
    message(request, { postMessage: vi.fn() });
    message(request, parent, 'https://wrong.test');
    expect(parent.postMessage).not.toHaveBeenCalled();
    message(request);
    expect(capture).not.toHaveBeenCalled();
    message({ type: 'maverick.app.visibility-changed', visible: false });
    const release = preventMaverickAppHibernation();
    message(request);
    expect(capture).not.toHaveBeenCalled();
    release(); release();
    message(request);
    expect(parent.postMessage).toHaveBeenLastCalledWith({ type: 'maverick.app.hibernated', app_id: 'chat', request_id: 'one', snapshot }, 'https://shell.test');
    media.push({ paused: false, currentTime: 0 });
    message(request);
    expect(parent.postMessage.mock.lastCall?.[0].snapshot).toBeNull();
    media[0] = { paused: true, currentTime: 42 };
    message(request);
    expect(parent.postMessage.mock.lastCall?.[0].snapshot).toBeNull();
    media.length = 0;
    capture.mockReturnValueOnce({ params: {}, state: { draft: 'x'.repeat(MAX_APP_SNAPSHOT_BYTES) } } as typeof snapshot);
    message(request);
    expect(parent.postMessage.mock.lastCall?.[0].snapshot).toBeNull();
    const resume = { type: 'maverick.app.resume', app_id: 'chat', request_id: 'one', snapshot, navigation: { thread_id: 'thread-b' } };
    message(resume); message(resume);
    await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
    expect(restore).toHaveBeenCalledExactlyOnceWith(snapshot, { thread_id: 'thread-b' });
    expect(parent.postMessage.mock.lastCall?.[0].type).toBe('maverick.app.resumed');
  } finally { dispose(); }
});
