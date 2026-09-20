import { afterEach, expect, it, vi } from 'vitest';
import { observeMaverickVisibility, maverickAppIsVisible } from '../src/appVisibility';

afterEach(() => vi.unstubAllGlobals());

it('intersects exact-parent visibility, document visibility and connectivity for all consumers', () => {
  const parent = {};
  const target = Object.assign(new EventTarget(), { parent, location: { origin: 'https://frame.test' },
    __MAVERICK_PLATFORM_ORIGIN__: 'https://shell.test' });
  const document = Object.assign(new EventTarget(), { hidden: false });
  const navigator = { onLine: true };
  vi.stubGlobal('window', target);
  vi.stubGlobal('document', document);
  vi.stubGlobal('navigator', navigator);
  const changed = vi.fn();
  const dispose = observeMaverickVisibility(changed);
  const message = (visible: boolean, source = parent) => target.dispatchEvent(Object.assign(new Event('message'), {
    data: { type: 'maverick.app.visibility-changed', visible }, origin: 'https://shell.test', source,
  }));
  try {
    message(false, {});
    expect(maverickAppIsVisible()).toBe(true);
    message(false);
    const late = vi.fn();
    const disposeLate = observeMaverickVisibility(late);
    expect(late).toHaveBeenCalledExactlyOnceWith(false);
    disposeLate();
    document.hidden = true;
    document.dispatchEvent(new Event('visibilitychange'));
    message(true);
    expect(maverickAppIsVisible()).toBe(false);
    navigator.onLine = false;
    document.hidden = false;
    document.dispatchEvent(new Event('visibilitychange'));
    expect(maverickAppIsVisible()).toBe(false);
    navigator.onLine = true;
    target.dispatchEvent(new Event('online'));
    expect(changed.mock.calls).toEqual([[true], [false], [true]]);
  } finally { dispose(); }
});
