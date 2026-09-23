import { describe, expect, it } from 'vitest';
import { isStandaloneWebApp, requestParentExternalUrl } from '../src/externalUrlBroker';

function messageTarget() {
  const messages: Array<{ message: unknown; targetOrigin: string }> = [];
  return {
    messages,
    target: {
      postMessage(message: unknown, targetOrigin: string) {
        messages.push({ message, targetOrigin });
      },
    },
  };
}

describe('external URL broker client', () => {
  it('recognizes both standard and iOS standalone signals', () => {
    expect(isStandaloneWebApp(true, false)).toBe(true);
    expect(isStandaloneWebApp(false, true)).toBe(true);
    expect(isStandaloneWebApp(false, false)).toBe(false);
  });

  it('posts only absolute HTTP(S) URLs to the parent shell', () => {
    const parent = messageTarget();
    const currentWindow = { __MAVERICK_PLATFORM_ORIGIN__: 'https://maverick.test' };

    expect(requestParentExternalUrl('javascript:alert(1)', { currentWindow, parentWindow: parent.target })).toBe(false);
    expect(requestParentExternalUrl('https://example.com/path', {
      currentWindow,
      ownerAppId: 'calendar',
      parentWindow: parent.target,
      widgetId: 'calendar-sidebar-footer',
    })).toBe(true);

    expect(parent.messages).toEqual([{
      message: {
        type: 'maverick.app.external-url',
        disposition: 'new-window',
        owner_app_id: 'calendar',
        widget_id: 'calendar-sidebar-footer',
        url: 'https://example.com/path',
      },
      targetOrigin: 'https://maverick.test',
    }]);
  });

  it('leaves top-level pages to their native anchor fallback', () => {
    const page = messageTarget();
    expect(requestParentExternalUrl('https://example.com', {
      currentWindow: page.target,
      parentWindow: page.target,
    })).toBe(false);
    expect(page.messages).toEqual([]);
  });
});
