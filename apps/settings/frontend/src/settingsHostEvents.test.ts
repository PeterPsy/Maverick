import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest';
import { bindSettingsHostEvents } from './settingsHostEvents';

describe('Settings shell navigation', () => {
  const shellOrigin = 'https://maverick.test';
  const frameOrigin = 'https://settings.frames.maverick.test';
  let frame: EventTarget & { parent: Window; location: { origin: string }; __MAVERICK_PLATFORM_ORIGIN__: string };
  let parent: Window;
  let context: { navigate: Mock<(params: Record<string, unknown>) => void>; visibilityChanged: Mock<(visible: boolean) => void> };

  beforeEach(() => {
    parent = { postMessage: vi.fn() } as unknown as Window;
    frame = Object.assign(new EventTarget(), {
      parent, location: { origin: frameOrigin }, __MAVERICK_PLATFORM_ORIGIN__: shellOrigin,
    });
    vi.stubGlobal('window', frame);
    vi.stubGlobal('document', Object.assign(new EventTarget(), { hidden: false }));
    context = { navigate: vi.fn(), visibilityChanged: vi.fn() };
    bindSettingsHostEvents(context);
  });

  afterEach(() => vi.unstubAllGlobals());

  function message(data: unknown, origin = shellOrigin, source = parent) {
    const event = new Event('message');
    Object.assign(event, { data, origin, source });
    frame.dispatchEvent(event);
  }

  it('changes pages when the shell navigates an isolated Settings frame', () => {
    for (const page of ['users', 'workspace-access', 'learning', 'platform-settings']) {
      const params = { app_page: `pages/${page}`, page_id: page };
      message({ type: 'maverick.app.navigate', app_id: 'settings', params });
      expect(context.navigate).toHaveBeenLastCalledWith(params);
    }
    expect(context.navigate).toHaveBeenCalledTimes(4);
  });

  it('rejects other origins, sources, apps, and relay duplicates', () => {
    const navigation = { type: 'maverick.app.navigate', app_id: 'settings', params: { page_id: 'users' } };
    message(navigation, 'https://untrusted.test');
    message(navigation, shellOrigin, {} as Window);
    message(navigation, frameOrigin, frame as unknown as Window);
    message({ ...navigation, app_id: 'chat' });
    expect(context.navigate).not.toHaveBeenCalled();
  });

  it('receives visibility changes from the isolated frame parent', () => {
    message({ type: 'maverick.app.visibility-changed', app_id: 'settings', visible: false });
    expect(context.visibilityChanged).toHaveBeenLastCalledWith(false);
    message({ type: 'maverick.app.visibility-changed', app_id: 'settings', visible: true });
    expect(context.visibilityChanged).toHaveBeenLastCalledWith(true);
  });
});
