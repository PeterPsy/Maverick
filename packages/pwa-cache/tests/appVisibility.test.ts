import { afterEach, expect, it, vi } from 'vitest';
import { observeLoopinoVisibility, loopinoAppIsVisible } from '../src/appVisibility';

afterEach(() => vi.unstubAllGlobals());

it('intersects exact-parent visibility, document visibility and connectivity for all consumers', () => {
  const parent = {};
  const target = Object.assign(new EventTarget(), { parent, location: { origin: 'https://frame.test' },
    __LOOPINO_PLATFORM_ORIGIN__: 'https://shell.test' });
  const document = Object.assign(new EventTarget(), { hidden: false });
  const navigator = { onLine: true };
  vi.stubGlobal('window', target);
  vi.stubGlobal('document', document);
  vi.stubGlobal('navigator', navigator);
  const changed = vi.fn();
  const dispose = observeLoopinoVisibility(changed);
  const foreground = vi.fn();
  const disposeForeground = observeLoopinoVisibility(foreground, { requireOnline: false });
  const message = (visible: boolean, source = parent) => target.dispatchEvent(Object.assign(new Event('message'), {
    data: { type: 'loopino.app.visibility-changed', visible }, origin: 'https://shell.test', source,
  }));
  try {
    message(false, {});
    expect(loopinoAppIsVisible()).toBe(true);
    message(false);
    const late = vi.fn();
    const disposeLate = observeLoopinoVisibility(late);
    expect(late).toHaveBeenCalledExactlyOnceWith(false);
    disposeLate();
    document.hidden = true;
    document.dispatchEvent(new Event('visibilitychange'));
    message(true);
    expect(loopinoAppIsVisible()).toBe(false);
    navigator.onLine = false;
    target.dispatchEvent(new Event('offline'));
    document.hidden = false;
    document.dispatchEvent(new Event('visibilitychange'));
    expect(loopinoAppIsVisible()).toBe(false);
    expect(loopinoAppIsVisible({ requireOnline: false })).toBe(true);
    message(false);
    message(true);
    navigator.onLine = true;
    target.dispatchEvent(new Event('online'));
    expect(changed.mock.calls).toEqual([[true], [false], [true]]);
    expect(foreground.mock.calls).toEqual([[true], [false], [true], [false], [true]]);
  } finally { dispose(); disposeForeground(); }
});
